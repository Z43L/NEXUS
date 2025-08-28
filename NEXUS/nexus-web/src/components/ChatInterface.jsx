import React, { useState, useRef } from 'react';
import { NexusClient } from 'nexus-sdk-js';

const ChatInterface = ({ apiKey }) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const client = useRef(new NexusClient({ apiKey }));

  const handleSend = async () => {
    if (!input.trim()) return;
    
    const userMessage = {
      role: 'user',
      content: input,
      timestamp: new Date()
    };
    
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);
    
    try {
      const newMessages = [...messages, userMessage];
      let fullResponse = '';
      
      for await (const chunk of client.current.chatStream(newMessages)) {
        fullResponse += chunk;
        
        // Actualizar el último mensaje con el chunk recibido
        setMessages(prev => {
          const lastMessage = prev[prev.length - 1];
          if (lastMessage.role === 'assistant') {
            return [...prev.slice(0, -1), {
              ...lastMessage,
              content: fullResponse
            }];
          } else {
            return [...prev, {
              role: 'assistant',
              content: fullResponse,
              timestamp: new Date()
            }];
          }
        });
      }
    } catch (error) {
      console.error('Chat error:', error);
      setMessages(prev => [...prev, {
        role: 'system',
        content: `Error: ${error.message}`,
        timestamp: new Date()
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="chat-interface">
      <div className="messages">
        {messages.map((msg, index) => (
          <div key={index} className={`message ${msg.role}`}>
            <div className="message-content">{msg.content}</div>
            <div className="message-timestamp">
              {msg.timestamp.toLocaleTimeString()}
            </div>
          </div>
        ))}
      </div>
      
      <div className="input-area">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleSend()}
          disabled={isLoading}
          placeholder="Ask NEXUS anything..."
        />
        <button onClick={handleSend} disabled={isLoading}>
          {isLoading ? 'Thinking...' : 'Send'}
        </button>
      </div>
    </div>
  );
};

export default ChatInterface;