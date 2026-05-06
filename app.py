from flask import Flask, render_template
from flask_socketio import SocketIO
import time
import threading
import feedparser
from textblob import TextBlob
from transformers import pipeline
import torch

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- INITIALIZE GLOBAL DATA ---
latest_news = []

# --- INITIALIZE AI AGENT ---
# Detects your RTX 30-series GPU
device = 0 if torch.cuda.is_available() else -1
print(f">>> System Check: Using {'GPU' if device == 0 else 'CPU'} for AI Agent")

# Loading the 'Zero-Shot Classification' model[cite: 2]
print(">>> Loading AI Model into VRAM... please wait.")
analyst_agent = pipeline("zero-shot-classification", 
                         model="valhalla/distilbart-mnli-12-1", 
                         device=device)
print(">>> MODEL READY! GPU IS ARMED.")

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

# --- SOCKET EVENTS ---
@socketio.on('connect')
def handle_connect():
    print(">>> Browser connected! Sending history...")
    for news in latest_news:
        socketio.emit('new_insight', news)

@socketio.on('ask_agent')
def handle_ask(data):
    question = data.get('question', '')
    print(f">>> Processing Question: {question}")
    
    # Use top 2 news items for context[cite: 2]
    context = ". ".join([n['title'] for n in latest_news[:2]])

    # Map labels to human-readable insights
    interpretations = {
        "risk": "I've detected some potential market risk or cautionary signals in the latest AI news.",
        "investment": "The current trend suggests a heavy focus on AI capital, funding, and growth.",
        "innovation": "We are seeing a major technological breakthrough or a pivot in AI research."
    }

    try:
        # GPU Inference Task[cite: 2]
        result = analyst_agent(question + " context: " + context, 
                              candidate_labels=["investment", "risk", "innovation"])
        
        top_label = result['labels'][0]
        confidence = round(result['scores'][0] * 100)
        
        # Build the final descriptive answer
        human_answer = f"{interpretations[top_label]} (Confidence: {confidence}%)"
        print(f">>> {human_answer}")
        
        # Emit formatted answer to browser[cite: 1, 2]
        socketio.emit('agent_answer', {'answer': human_answer})
        print(">>> Answer Emitted to Browser")

    except Exception as e:
        print(f">>> ERROR DURING GPU TASK: {e}")
        socketio.emit('agent_answer', {'answer': f"Local Error: {str(e)[:50]}"})

# --- BACKGROUND FEED SCRAPER ---
def background_agent_task():
    FEED_URL = "https://techcrunch.com/feed/"
    seen_titles = set()
    CAREER_KEYWORDS = ['ai', 'llm', 'machine learning', 'python', 'neural', 'nvidia', 'gpu', 'openai']

    while True:
        try:
            feed = feedparser.parse(FEED_URL)
            for entry in feed.entries[:5]:
                if entry.title not in seen_titles:
                    seen_titles.add(entry.title)
                    
                    full_text = f"{entry.title}. {entry.summary.split('<')[0]}"
                    analysis = TextBlob(full_text)
                    polarity = analysis.sentiment.polarity
                    scaled_score = round(((polarity + 1) * 4.5) + 1, 1)
                    
                    is_priority = any(word in full_text.lower() for word in CAREER_KEYWORDS)
                    
                    label = "Neutral"
                    if polarity > 0.1: label = "Positive"
                    elif polarity < -0.1: label = "Negative"

                    news_update = {
                        "title": "🔥 [PRIORITY] " + entry.title if is_priority else entry.title,
                        "summary": entry.summary.split('<')[0][:150] + "...",
                        "sentiment": label,
                        "score": scaled_score,
                        "priority": is_priority
                    }
                    
                    latest_news.insert(0, news_update)
                    if len(latest_news) > 10: latest_news.pop()
                    socketio.emit('new_insight', news_update)
            
        except Exception as e:
            print(f">>> Agent Error: {e}")
        time.sleep(20)

# --- START THE SYSTEM ---
if __name__ == '__main__':
    thread = threading.Thread(target=background_agent_task, daemon=True)
    thread.start()
    
    print(">>> Server starting at http://127.0.0.1:5000")
    # 'allow_unsafe_werkzeug' ensures stability on Windows[cite: 2]
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)