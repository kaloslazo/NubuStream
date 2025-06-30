#!/usr/bin/env python3
"""
Prueba simple del sistema de chat
"""

import asyncio
import websockets
import json
import time


async def simple_client_test():
    """Test simple de cliente"""
    print("🧪 Iniciando test simple del cliente...")

    try:
        # Conectar al servidor
        print("📡 Conectando a ws://localhost:8765...")
        websocket = await websockets.connect("ws://localhost:8765")
        print("✅ Conexión WebSocket establecida")

        # Enviar autenticación
        auth_data = {"username": "TestUser", "role": "viewer", "room_id": "test_room"}

        print("🔑 Enviando datos de autenticación...")
        await websocket.send(json.dumps(auth_data))

        # Esperar confirmación
        print("⏳ Esperando confirmación del servidor...")
        response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        data = json.loads(response)

        print(f"📨 Respuesta del servidor: {data}")

        if data.get("type") == "connection_confirmed":
            print("✅ Autenticación exitosa!")
            user_id = data.get("user_id")

            # Enviar un mensaje de prueba
            test_message = {"type": "chat_message", "content": "¡Hola desde el test simple!"}

            print("💬 Enviando mensaje de prueba...")
            await websocket.send(json.dumps(test_message))

            # Solicitar estado del sistema
            status_request = {"type": "system_status"}
            print("📊 Solicitando estado del sistema...")
            await websocket.send(json.dumps(status_request))

            # Escuchar respuestas por unos segundos
            print("👂 Escuchando respuestas del servidor...")
            end_time = time.time() + 5  # Escuchar por 5 segundos

            while time.time() < end_time:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    data = json.loads(message)
                    print(f"📨 Mensaje recibido: {data.get('type', 'unknown')}")

                    if data.get("type") == "system_status_response":
                        status = data.get("status", {})
                        print(f"📊 Estado del sistema:")
                        for key, value in status.items():
                            print(f"   {key}: {value}")

                except asyncio.TimeoutError:
                    continue  # No hay mensajes, continuar

        else:
            print(f"❌ Error en autenticación: {data}")

        # Cerrar conexión
        await websocket.close()
        print("🔌 Conexión cerrada")
        print("✅ Test completado exitosamente!")

    except ConnectionRefusedError:
        print("❌ Error: No se pudo conectar al servidor")
        print("💡 Asegúrate de que el servidor esté ejecutándose:")
        print("   python3 streaming_chat_server.py")
        return False

    except asyncio.TimeoutError:
        print("❌ Error: Timeout esperando respuesta del servidor")
        return False

    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        return False

    return True


async def test_multiple_clients():
    """Test con múltiples clientes"""
    print("\n🧪 Test con múltiples clientes...")

    async def create_client(username, room_id="test_room"):
        """Crear un cliente individual"""
        try:
            websocket = await websockets.connect("ws://localhost:8765")

            auth_data = {"username": username, "role": "viewer", "room_id": room_id}

            await websocket.send(json.dumps(auth_data))
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(response)

            if data.get("type") == "connection_confirmed":
                print(f"✅ {username} conectado")

                # Enviar un mensaje
                message = {"type": "chat_message", "content": f"Mensaje desde {username}"}
                await websocket.send(json.dumps(message))

                # Escuchar un poco
                await asyncio.sleep(2)

                await websocket.close()
                return True
            else:
                print(f"❌ {username} falló la autenticación")
                return False

        except Exception as e:
            print(f"❌ Error con {username}: {e}")
            return False

    # Crear múltiples clientes concurrentemente
    tasks = [create_client("Usuario1"), create_client("Usuario2"), create_client("Usuario3")]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    successful = sum(1 for r in results if r is True)

    print(f"📊 Resultado: {successful}/3 clientes conectados exitosamente")
    return successful == 3


def main():
    """Función principal"""
    print("🚀 Prueba Simple del Sistema de Chat")
    print("=" * 50)

    # Test 1: Cliente simple
    try:
        result1 = asyncio.run(simple_client_test())
    except KeyboardInterrupt:
        print("\n🛑 Test interrumpido por el usuario")
        return

    if not result1:
        print("❌ Test simple falló")
        return

    # Test 2: Múltiples clientes
    try:
        result2 = asyncio.run(test_multiple_clients())
    except KeyboardInterrupt:
        print("\n🛑 Test interrumpido por el usuario")
        return

    if result2:
        print("🎉 ¡Todos los tests pasaron exitosamente!")
    else:
        print("⚠️ Algunos tests fallaron")


if __name__ == "__main__":
    main()
