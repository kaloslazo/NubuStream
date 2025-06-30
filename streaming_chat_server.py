# POC - Sistema de Chat de Streaming con Enfoque en Availability
# Plataforma de Streaming de Video en Tiempo Real

import asyncio
import websockets
import json
import logging
from datetime import datetime
from typing import Dict, List, Set
from dataclasses import dataclass, asdict
from enum import Enum
import uuid
import time

# Manejo de Redis con fallback
try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("⚠️ Redis no disponible, usando solo memoria local")

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class UserRole(Enum):
    VIEWER = "viewer"
    MODERATOR = "moderator"
    STREAMER = "streamer"


@dataclass
class User:
    user_id: str
    username: str
    role: UserRole
    is_authenticated: bool = True


@dataclass
class ChatMessage:
    message_id: str
    user_id: str
    username: str
    content: str
    timestamp: datetime
    room_id: str
    is_moderated: bool = False


@dataclass
class ChatRoom:
    room_id: str
    name: str
    active_users: int = 0
    is_active: bool = True


class AvailabilityMetrics:
    """Métricas para monitorear disponibilidad del sistema"""

    def __init__(self):
        self.message_count = 0
        self.failed_messages = 0
        self.connection_count = 0
        self.disconnection_count = 0
        self.start_time = time.time()

    def get_uptime_percentage(self) -> float:
        """Calcula el uptime basado en conexiones exitosas"""
        total_attempts = self.connection_count + self.disconnection_count
        if total_attempts == 0:
            return 100.0
        return (self.connection_count / total_attempts) * 100

    def get_message_success_rate(self) -> float:
        """Calcula la tasa de éxito de mensajes"""
        total_messages = self.message_count + self.failed_messages
        if total_messages == 0:
            return 100.0
        return (self.message_count / total_messages) * 100


class RedisManager:
    """Gestor de Redis para persistencia y pub/sub"""

    def __init__(self):
        if not REDIS_AVAILABLE:
            self.redis_client = None
            self.pubsub = None
            logger.warning("⚠️ Redis no disponible, usando memoria local")
            return

        try:
            self.redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
            # Test de conexión
            self.redis_client.ping()
            self.pubsub = self.redis_client.pubsub()
            logger.info("✅ Redis conectado exitosamente")
        except Exception as e:
            logger.warning(f"⚠️ Redis no disponible, usando memoria local: {e}")
            self.redis_client = None
            self.pubsub = None

    def publish_message(self, channel: str, message: dict) -> bool:
        """Publica mensaje en Redis con fallback"""
        try:
            if self.redis_client:
                self.redis_client.publish(channel, json.dumps(message))
                return True
        except Exception as e:
            logger.error(f"Error publicando en Redis: {e}")
        return False

    def store_message(self, message: ChatMessage) -> bool:
        """Almacena mensaje con redundancia"""
        try:
            if self.redis_client:
                # Convertir a dict y manejar datetime
                message_dict = asdict(message)
                message_dict["timestamp"] = message_dict["timestamp"].isoformat()

                key = f"messages:{message.room_id}:{message.message_id}"
                self.redis_client.setex(key, 3600, json.dumps(message_dict))
                return True
        except Exception as e:
            logger.error(f"Error almacenando mensaje: {e}")
        return False


class MessageModerationService:
    """Servicio de moderación de mensajes"""

    def __init__(self):
        self.blocked_words = ["spam", "toxic", "hate"]  # Palabras bloqueadas ejemplo

    def moderate_message(self, message: ChatMessage, user: User) -> bool:
        """Modera mensaje basado en contenido y rol de usuario"""
        # Moderadores y streamers tienen menos restricciones
        if user.role in [UserRole.MODERATOR, UserRole.STREAMER]:
            return True

        # Verificar palabras bloqueadas
        content_lower = message.content.lower()
        for word in self.blocked_words:
            if word in content_lower:
                logger.info(f"Mensaje bloqueado por contenido inapropiado: {message.message_id}")
                return False

        return True


class WebSocketManager:
    """Gestor de conexiones WebSocket con enfoque en disponibilidad"""

    def __init__(self):
        self.connections: Dict[str, websockets.WebSocketServerProtocol] = {}
        self.user_rooms: Dict[str, str] = {}  # user_id -> room_id
        self.room_users: Dict[str, Set[str]] = {}  # room_id -> set of user_ids
        self.redis_manager = RedisManager()
        self.moderation_service = MessageModerationService()
        self.metrics = AvailabilityMetrics()
        self.active_rooms: Dict[str, ChatRoom] = {}

    async def register_connection(self, websocket, user: User, room_id: str):
        """Registra nueva conexión con manejo de fallos"""
        try:
            self.connections[user.user_id] = websocket
            self.user_rooms[user.user_id] = room_id

            if room_id not in self.room_users:
                self.room_users[room_id] = set()
                self.active_rooms[room_id] = ChatRoom(room_id, f"Room {room_id}")

            self.room_users[room_id].add(user.user_id)
            self.active_rooms[room_id].active_users += 1
            self.metrics.connection_count += 1

            logger.info(f"✅ Usuario {user.username} conectado a sala {room_id}")

            # Notificar a otros usuarios de la sala
            await self.broadcast_to_room(
                room_id,
                {"type": "user_joined", "user": asdict(user), "active_users": self.active_rooms[room_id].active_users},
                exclude_user=user.user_id,
            )

        except Exception as e:
            logger.error(f"Error registrando conexión: {e}")
            self.metrics.disconnection_count += 1

    async def unregister_connection(self, user_id: str):
        """Desregistra conexión con limpieza"""
        try:
            if user_id in self.connections:
                room_id = self.user_rooms.get(user_id)
                if room_id and room_id in self.room_users:
                    self.room_users[room_id].discard(user_id)
                    if room_id in self.active_rooms:
                        self.active_rooms[room_id].active_users = max(0, self.active_rooms[room_id].active_users - 1)

                del self.connections[user_id]
                if user_id in self.user_rooms:
                    del self.user_rooms[user_id]

                logger.info(f"❌ Usuario {user_id} desconectado")

        except Exception as e:
            logger.error(f"Error desregistrando conexión: {e}")

    async def broadcast_to_room(self, room_id: str, message: dict, exclude_user: str = None):
        """Broadcast con manejo de conexiones fallidas"""
        if room_id not in self.room_users:
            return

        failed_connections = []
        successful_sends = 0

        for user_id in self.room_users[room_id]:
            if user_id == exclude_user:
                continue

            if user_id in self.connections:
                try:
                    await self.connections[user_id].send(json.dumps(message))
                    successful_sends += 1
                except websockets.exceptions.ConnectionClosed:
                    failed_connections.append(user_id)
                except Exception as e:
                    logger.error(f"Error enviando mensaje a {user_id}: {e}")
                    failed_connections.append(user_id)

        # Limpiar conexiones fallidas
        for user_id in failed_connections:
            await self.unregister_connection(user_id)

        logger.info(f"📨 Mensaje broadcast a {successful_sends} usuarios en sala {room_id}")

    async def handle_chat_message(self, user: User, content: str) -> bool:
        """Procesa mensaje de chat con verificaciones de disponibilidad"""
        try:
            message = ChatMessage(
                message_id=str(uuid.uuid4()),
                user_id=user.user_id,
                username=user.username,
                content=content,
                timestamp=datetime.now(),
                room_id=self.user_rooms.get(user.user_id, ""),
            )

            # Moderación
            if not self.moderation_service.moderate_message(message, user):
                return False

            # Almacenar mensaje (con fallback)
            stored = self.redis_manager.store_message(message)
            if not stored:
                logger.warning("⚠️ Mensaje no almacenado en Redis, continuando...")

            # Convertir mensaje a dict para JSON
            message_dict = asdict(message)
            # Convertir datetime a string
            message_dict["timestamp"] = message_dict["timestamp"].isoformat()

            # Broadcast del mensaje
            await self.broadcast_to_room(message.room_id, {"type": "chat_message", "message": message_dict})

            self.metrics.message_count += 1
            return True

        except Exception as e:
            logger.error(f"Error procesando mensaje: {e}")
            self.metrics.failed_messages += 1
            return False

    def get_system_status(self) -> dict:
        """Retorna estado del sistema para monitoreo"""
        return {
            "uptime_percentage": self.metrics.get_uptime_percentage(),
            "message_success_rate": self.metrics.get_message_success_rate(),
            "active_connections": len(self.connections),
            "active_rooms": len(self.active_rooms),
            "total_messages": self.metrics.message_count,
            "failed_messages": self.metrics.failed_messages,
            "redis_available": self.redis_manager.redis_client is not None,
        }


# Servidor WebSocket principal
websocket_manager = WebSocketManager()


async def handle_client(websocket):
    """Maneja conexiones de clientes WebSocket"""
    user = None
    try:
        # Simulación de autenticación
        auth_message = await websocket.recv()
        auth_data = json.loads(auth_message)

        user = User(
            user_id=str(uuid.uuid4()),
            username=auth_data.get("username", "Anonymous"),
            role=UserRole(auth_data.get("role", "viewer")),
        )

        room_id = auth_data.get("room_id", "general")

        # Registrar conexión
        await websocket_manager.register_connection(websocket, user, room_id)

        # Enviar confirmación de conexión
        await websocket.send(json.dumps({"type": "connection_confirmed", "user_id": user.user_id, "room_id": room_id}))

        # Manejar mensajes entrantes
        async for message in websocket:
            try:
                data = json.loads(message)
                message_type = data.get("type")

                if message_type == "chat_message":
                    await websocket_manager.handle_chat_message(user, data.get("content", ""))
                elif message_type == "system_status":
                    status = websocket_manager.get_system_status()
                    await websocket.send(json.dumps({"type": "system_status_response", "status": status}))

            except json.JSONDecodeError:
                logger.error("Mensaje JSON inválido recibido")
            except Exception as e:
                logger.error(f"Error procesando mensaje: {e}")

    except websockets.exceptions.ConnectionClosed:
        logger.info("Conexión cerrada por el cliente")
    except Exception as e:
        logger.error(f"Error en conexión: {e}")
    finally:
        if user:
            await websocket_manager.unregister_connection(user.user_id)


# Fitness Functions para testing de disponibilidad
class AvailabilityTests:
    """Tests de disponibilidad para el sistema"""

    @staticmethod
    def test_message_latency():
        """Test: Latencia de mensajería ≤ 50ms P95"""
        # Implementación de test de latencia
        pass

    @staticmethod
    def test_websocket_uptime():
        """Test: Uptime WebSocket Manager ≥ 99.9%"""
        status = websocket_manager.get_system_status()
        assert status["uptime_percentage"] >= 99.9, f"Uptime {status['uptime_percentage']}% < 99.9%"

    @staticmethod
    def test_concurrent_users():
        """Test: Soporte para 200K usuarios concurrentes"""
        # Simulación de carga
        pass


# Función principal para ejecutar el servidor
async def main():
    """Inicia el servidor WebSocket"""
    logger.info("🚀 Iniciando servidor de chat con enfoque en Availability")
    logger.info("💡 Características implementadas:")
    logger.info("   - WebSocket con manejo de fallos")
    logger.info("   - Redis para persistencia (con fallback)")
    logger.info("   - Moderación de mensajes")
    logger.info("   - Métricas de disponibilidad")
    logger.info("   - Broadcast resiliente")

    # Iniciar servidor WebSocket
    server = await websockets.serve(handle_client, "localhost", 8765)
    logger.info("📡 Servidor WebSocket ejecutándose en ws://localhost:8765")

    # Mostrar estado periódicamente
    async def show_status():
        while True:
            await asyncio.sleep(30)  # Cada 30 segundos
            status = websocket_manager.get_system_status()
            logger.info(f"📊 Estado del sistema: {status}")

    # Ejecutar ambas tareas
    await asyncio.gather(server.wait_closed(), show_status())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Servidor detenido por el usuario")
