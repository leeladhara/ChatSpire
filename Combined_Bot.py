from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
import json
from fastapi.responses import JSONResponse
from slackeventsapi import SlackEventAdapter
from flask import request
from loguru import logger
from builders import build_write_index, build_read_index, reset, build_service_context
from llama_hub.confluence.base import ConfluenceReader
from botbuilder.schema import Activity, CardAction, HeroCard, ActivityTypes, Attachment, AttachmentLayoutTypes
from pydantic import BaseModel
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier
from starlette.requests import Request
from slack_sdk.errors import SlackApiError
import time
from dotenv import load_dotenv
import os
import traceback
import aiohttp
import asyncio

# Load environment variables
load_dotenv()

app = FastAPI()

# Configure logger
logger.add("bot_debug.log", rotation="500 MB")

# Build service context
build_service_context()

# Load credentials
TEAMS_APP_ID = os.getenv('TEAMS_APP_ID')
TEAMS_APP_PASSWORD = os.getenv('TEAMS_APP_PASSWORD')
SLACK_BOT_TOKEN = 'xxx'

# Slack-specific code (unchanged from the first document)

@app.post("/googlewebhook")
async def google_chat_webhook(request: Request):
    body = await request.json()
    print("Received message:", json.dumps(body, indent=2))

    message_text = body.get("message", {}).get("text", "")

    question = message_text.replace("@chatbot", "")

    index = build_read_index()
    query_engine = index.as_query_engine()
    response = query_engine.query(question)

    response_text = f"{response.response }\n\nI used these sources:\n" + "\n".join(
        [
            f"<{page_info['url']}|{page_info['title']}>"
            for _, page_info in (response.metadata or {}).items()
        ]
    )
    
    return {"text": response_text}

class SlackEvent(BaseModel):
    token: str = ""
    team_id: str = ""
    api_app_id: str = ""
    event: dict = {}
    type: str = ""
    event_id: str = ""
    event_time: int = 5
    authed_users: list = []
    challenge: str = ""
    block: str = ""
    thread_ts:str = ""

def process_question(payload, question, channel_id):
    if payload.type == "url_verification":
        return {"challenge": payload.event.get("challenge")}

    if payload.type == "event_callback":
        event = payload.event
        
        if event.get("type") == "app_mention":
            channel_id = event.get("channel")
            message_text = event.get("text")
            question = message_text.replace("<@U060WJEC0RX>", "")
            print(question)

    index = build_read_index()
    query_engine = index.as_query_engine()
    response = query_engine.query(question)

    response_text = f"{response.response }\n\nI used these sources:\n" + "\n".join(
        [
            f"<{page_info['url']}|{page_info['title']}>"
            for _, page_info in (response.metadata or {}).items()
        ]
    )

    answer_blocks = [
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": response_text
        }
    }
]
    client = WebClient(token=SLACK_BOT_TOKEN)
    response = client.chat_postMessage(channel=channel_id, text = response_text)

def send_feedback_message(channel_id, thread_ts):
    try:
        client = WebClient(token=SLACK_BOT_TOKEN)
        response = client.chat_postMessage(
            channel=channel_id,
            text = "capllama needs some feedback",
            thread_ts=thread_ts,
            attachments=[
                {
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Feedback Request"
            }
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": "How was my response? Your feedback is much appreciated."
                }
            ]
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "👍 Satisfactory"
                    },
                    "style": "primary",
                    "value": "Satisfactory"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "👎 Unsatisfactory"
                    },
                    "style": "danger",
                    "value": "Unsatisfactory"
                }
            ]
        }
    ]
}
            ]
        )
        return response["ts"]
    except SlackApiError as e:
        print(f"Error: {e.response['error']}")

def send_ack(payload):
    if payload.event.get("type") == "app_mention":
        return JSONResponse(content={"error": "Processing the Request"},headers={"x-slack-no-retry": "1"})

@app.post("/slackWebhook")
async def handle_events(request: Request, payload: SlackEvent, background_tasks: BackgroundTasks):
    question = payload.event.get("text").replace("<@U060WJEC0RX>", "")
    channel_id = payload.event.get("channel")

    # Process the question
    background_tasks.add_task(process_question, payload, question, channel_id)
    # Send immediate OK response to Slack
    return JSONResponse(content={"ok": False},headers={"x-slack-no-retry":"1"})

@app.post('/slackWebhook/actions')
async def handle_slack_actions(request: Request):
    try:
        form_data = await request.form()
        payload_data = form_data['payload']
        print(payload_data)
        # Parse the JSON-encoded payload
        payload_json = json.loads(payload_data)

        # Check if the payload type is 'block_actions'
        if payload_json['type'] == 'block_actions':
            action_type = payload_json['actions'][0]['type']

            # Check if the action type is 'button'
            if action_type == 'button':
                action_value = payload_json['actions'][0]['value']
                user_id = payload_json['user']['id']
                channel_id = payload_json['channel']['id']

                # Handle the button click based on action_value
                if action_value == 'Satisfactory':
                    response_message = f"User {user_id} found the response satisfactory."
                elif action_value == 'Unsatisfactory':
                    response_message = f"User {user_id} found the response unsatisfactory."
                else:
                    response_message = "Unknown action_value received."

                # Update your logic or store feedback data accordingly
                print(response_message)
                return JSONResponse(content={'message': response_message})
    except Exception as e:
        return JSONResponse(content={'message': f'Error handling payload: {e}'}, status_code=400)

# Microsoft Teams-specific code

async def get_access_token():
    url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": TEAMS_APP_ID,
        "client_secret": TEAMS_APP_PASSWORD,
        "scope": "https://api.botframework.com/.default"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data) as response:
            if response.status == 200:
                token_data = await response.json()
                return token_data['access_token']
            else:
                error_text = await response.text()
                raise Exception(f"Failed to get token: {error_text}")

@app.post("/api/messages")
async def messages(request: Request):
    body = await request.json()
    logger.info(f"Received request: {body}")

    try:
        activity = Activity().deserialize(body)
        logger.info(f"Deserialized activity: {activity}")

        if activity.type == ActivityTypes.message:
            await process_message(activity)
        else:
            logger.info(f"Received non-message activity: {activity.type}")

        return JSONResponse(content={'message': 'Activity processed'}, status_code=200)
    except Exception as e:
        logger.error(f"Error processing activity: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return JSONResponse(content={'message': f"Error processing activity: {str(e)}"}, status_code=500)

async def process_message(activity: Activity):
    try:
        if activity.text.startswith("Feedback:"):
            await process_feedback(activity)
        else:
            await process_teams_question(activity)
    except Exception as e:
        logger.error(f"Error in process_message: {e}\n{traceback.format_exc()}")
        await send_error_message(activity)

async def process_teams_question(activity: Activity):
    try:
        question = activity.text.replace("@ChatSpire", "").strip()
        index = build_read_index()
        query_engine = index.as_query_engine()
        response = query_engine.query(question)

        response_text = f"{response.response}\n\nI used these sources:\n" + "\n".join(
            [f"{page_info['title']}: {page_info['url']}" for _, page_info in (response.metadata or {}).items()]
        )

        card = HeroCard(
            title="Was this response helpful?",
            buttons=[
                CardAction(type="messageBack", title="Satisfactory", text="Feedback: Satisfactory", display_text="Satisfactory"),
                CardAction(type="messageBack", title="Unsatisfactory", text="Feedback: Unsatisfactory", display_text="Unsatisfactory")
            ]
        )
        attachment = Attachment(content_type="application/vnd.microsoft.card.hero", content=card)

        reply = Activity(
            type=ActivityTypes.message,
            text=response_text,
            attachment_layout=AttachmentLayoutTypes.list,
            attachments=[attachment],
            conversation=activity.conversation,
            recipient=activity.from_property,
            from_property=activity.recipient
        )

        logger.info(f"Sending reply: {reply}")
        await send_activity(activity.service_url, reply)
    except Exception as e:
        logger.error(f"Error in process_teams_question: {e}\n{traceback.format_exc()}")

async def process_feedback(activity: Activity):
    try:
        feedback_value = activity.text.replace("Feedback: ", "").strip()
        user_id = activity.from_property.id

        if feedback_value == "Satisfactory":
            response_message = f"User found the response satisfactory."
        elif feedback_value == "Unsatisfactory":
            response_message = f"User found the response unsatisfactory."
        else:
            response_message = "Unknown feedback value received."

        logger.info(response_message)

        reply = Activity(
            type=ActivityTypes.message,
            text=f"Thank you for your feedback. {response_message}",
            conversation=activity.conversation,
            recipient=activity.from_property,
            from_property=activity.recipient
        )

        logger.info(f"Sending feedback reply: {reply}")
        await send_activity(activity.service_url, reply)
    except Exception as e:
        logger.error(f"Error in process_feedback: {e}\n{traceback.format_exc()}")

async def send_activity(service_url: str, activity: Activity):
    try:
        logger.info(f"Attempting to send activity: {activity}")
        
        token = await get_access_token()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        url = f"{service_url}/v3/conversations/{activity.conversation.id}/activities"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=activity.serialize(), headers=headers) as response:
                if response.status == 200 or response.status == 201:
                    logger.info("Activity sent successfully")
                    return await response.json()
                else:
                    error_text = await response.text()
    except Exception as e:
        logger.error(f"Error sending activity: {e}\n{traceback.format_exc()}")
        raise

async def send_error_message(original_activity: Activity):
    error_message = Activity(
        type=ActivityTypes.message,
        text="I'm sorry, but I encountered an error while processing your request. Please try again later.",
        conversation=original_activity.conversation,
        recipient=original_activity.from_property,
        from_property=original_activity.recipient
    )
    await send_activity(original_activity.service_url, error_message)
