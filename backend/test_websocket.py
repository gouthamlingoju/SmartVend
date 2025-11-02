import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:8002/ws"
    async with websockets.connect(uri) as websocket:
        # Send registration message
        register_msg = {
            "type": "register",
            "machine_id": "M001",
            "api_key": "sv_001mmsg"
        }
        await websocket.send(json.dumps(register_msg))
        print("Sent registration message")
        
        # Wait for response
        response = await websocket.recv()
        print(f"Received: {response}")
        
        # Send status message
        status_msg = {
            "type": "status",
            "value": "active"
        }
        await websocket.send(json.dumps(status_msg))
        print("Sent status message")
        
        # Send fetch display message
        fetch_msg = {
            "type": "fetch_display"
        }
        await websocket.send(json.dumps(fetch_msg))
        print("Sent fetch display message")
        
        # Wait for response
        response = await websocket.recv()
        print(f"Received: {response}")
        
        # Keep connection alive for a few seconds to see heartbeat
        await asyncio.sleep(35)

asyncio.run(test_websocket())