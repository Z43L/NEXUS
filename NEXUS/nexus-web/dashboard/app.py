from flask import Flask, render_template, jsonify, request
import aiohttp
import asyncio
from datetime import datetime
import json

app = Flask(__name__)

class NexusWebDashboard:
    """Dashboard web para interacción con NEXUS"""
    
    def __init__(self, api_url: str):
        self.api_url = api_url
        self.session = None
    
    async def initialize(self):
        """Inicializa la sesión asíncrona"""
        self.session = aiohttp.ClientSession()
    
    async def get_user_info(self, api_key: str) -> Dict:
        """Obtiene información del usuario"""
        async with self.session.get(
            f"{self.api_url}/v1/auth/user",
            headers={"X-API-Key": api_key}
        ) as response:
            return await response.json()
    
    async def stream_chat(self, api_key: str, message: str, context: Dict = None):
        """Streaming de chat con NEXUS"""
        data = {
            "message": message,
            "context": context or {},
            "stream": True
        }
        
        async with self.session.post(
            f"{self.api_url}/v1/cognitive/chat",
            headers={"X-API-Key": api_key},
            json=data
        ) as response:
            async for line in response.content:
                if line:
                    yield line.decode().strip()

@app.route('/')
def index():
    """Página principal del dashboard"""
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
async def chat_endpoint():
    """Endpoint para chat con streaming"""
    api_key = request.headers.get('X-API-Key')
    data = request.json
    
    if not api_key:
        return jsonify({"error": "API key required"}), 401
    
    dashboard = NexusWebDashboard("https://api.nexus.ai")
    await dashboard.initialize()
    
    def generate():
        async def generate_async():
            async for chunk in dashboard.stream_chat(api_key, data['message'], data.get('context')):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        
        return generate_async()
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/knowledge', methods=['POST'])
async def upload_knowledge():
    """Endpoint para subir conocimiento"""
    api_key = request.headers.get('X-API-Key')
    data = request.json
    
    if not api_key:
        return jsonify({"error": "API key required"}), 401
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.nexus.ai/v1/knowledge/upload",
            headers={"X-API-Key": api_key},
            json=data
        ) as response:
            result = await response.json()
            return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)