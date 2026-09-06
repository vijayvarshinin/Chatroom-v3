from flask import Flask, render_template, request, url_for, session, redirect
from flask_socketio import join_room, leave_room, send, SocketIO, emit
import random
from string import ascii_uppercase
import os
from google import genai

# Setting up flask web server
# Initialise flask application
app = Flask(__name__)
app.config["SECRET_KEY"] = "dkfdjfhdjfydjfd" # Config flask app
socketio = SocketIO(app) # Setting up socketio

#initialize the AI Gemini client
ai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

rooms={}

#generate a room code
def generate_unique_code(length):
    while True:
        code = ""
        for _ in range(length):
            code += random.choice(ascii_uppercase)

        if code not in rooms:
            break
    return code


# Create route - homepage (create a new chatroom)
@app.route("/", methods=["POST", "GET"])
def home():
    session.clear()
    if request.method == "POST":
        name = request.form.get("name")
        code = request.form.get("code")
        join = request.form.get("join", False)
        create = request.form.get("create", False) #because buttons have an empty value

        if not name:
            return render_template("home.html", error="Please Enter a Name!", code=code, name=name)

        if join != False and not code:
            return render_template("home.html", error="Please Enter a Room Code!", code=code, name=name)

        #check if room exists or not
        room = code
        if create != False:
            room = generate_unique_code(4)
            #starting data
            rooms[room] = {"members": 0, "users": [], "messages": []}
        elif code not in rooms:
            return render_template("home.html", error="Room does not exist!", code=code, name=name)

        #storing data in session (temp store it in server)
        session["room"] = room
        session["name"] = name
        return redirect(url_for("room"))
    return render_template("home.html")

@app.route("/room")
def room():
    room = session.get("room")
    if room is None or session.get("name") is None or room not in rooms:
        return redirect(url_for("home"))
    
    return render_template("room.html", code=room, messages=rooms[room]["messages"])

#socketio handlers and AI integration
def handle_ai_responses(prompt, user_name, room):
    try:
        system_instruction = (
            f"You are a helpful chatroom assistant. You are answering a question from {user_name}. "
            f"Address {user_name} directly by name in your answer. Keep your response short and concise."
        )
        response = ai_client.models.generate_content(
            model="gemini-flash-latest",
            contents=f"{system_instruction}\n\nUser Question: {prompt}"
        )
        bot_reply = response.text
    except Exception as e:
        print(f"[AI ERROR] {e}")  # <-- add this so failures aren't silent
        bot_reply = f"Sorry {user_name}, I had trouble generating a response."

    bot_content = {"name": "AI Agent", "message": bot_reply}

    with app.app_context():
        socketio.emit("message", bot_content, to=room, namespace="/")  # <-- changed
        if room in rooms:
            rooms[room]["messages"].append(bot_content)

@socketio.on("message")
def message(data):
    room = session.get("room")

    #define name for AI agent
    name = session.get("name")

    #define usermsg 
    user_msg = data.get("data","")
    if room not in rooms:
        return

    content = {
        "name": session.get("name"),
        "message": user_msg
    }
    send(content, to=room)
    rooms[room]["messages"].append(content)
    print(f"{session.get('name')} said: {data['data']}")

    #check for @agent inside the same message
    if "@agent" in user_msg.lower():
        clean_prompt = user_msg.lower().replace("@agent", "").strip()
        if not clean_prompt:
            clean_prompt = 'Hello!'
        socketio.start_background_task(handle_ai_responses,clean_prompt,name, room)


#flask - socket
@socketio.on("connect")
def connect(auth):
    room = session.get("room")
    name = session.get("name")
    if not room or not name:
        return
    if room not in rooms:
        leave_room(room)
        return 
    #putting user in the room
    join_room(room)

    # Add user to active room list if not present
    if name not in rooms[room]["users"]:
        rooms[room]["users"].append(name)

    #keep track of the number of people in room (only here they are connected to the socket)
    rooms[room]["members"] +=1
    #send message to room
    send({"name": name, "message": "has entered the room"}, to=room)
    emit("update_users", {"users": rooms[room]["users"]}, to=room)
    print(f"{name} joined the {room}")

@socketio.on("disconnect")
def disconnect():
    room = session.get("room")
    name = session.get("name")
    leave_room(room)

    if room in rooms:
        rooms[room]["members"] -=1
        if name in rooms[room]["users"]:
            rooms[room]["users"].remove(name)
        send({"name": name, "message": "has left the room"}, to=room)
        print(f"{name} has left the {room}")
        emit("update_users", {"users": rooms[room]["users"]}, to=room)
        if rooms[room]["members"] <=0: #if there are no one in the room
            del rooms[room]
    
    
 

# Pass the app to socketio
if __name__ == "__main__":
    socketio.run(app, debug=True)