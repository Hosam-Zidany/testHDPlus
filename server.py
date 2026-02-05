import os
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
import json
from telegram import Update
from bot import TelegramBot, get_bot_token

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="Telegram Bot Webhook Server")

# Global bot instance
bot_instance = None


@app.on_event("startup")
async def startup_event():
    """Initialize the bot on startup"""
    global bot_instance
    try:
        bot_token = get_bot_token()
        if not bot_token:
            logger.error("BOT_TOKEN not found in environment variables")
            return

        bot_instance = TelegramBot(bot_token)
        logger.info("Bot instance initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize bot: {e}")


@app.get("/")
async def root():
    """Root endpoint for health check"""
    return {"status": "ok", "message": "Telegram bot webhook server is running"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "bot_initialized": bot_instance is not None}


@app.post("/webhook")
async def webhook(request: Request):
    """Handle incoming Telegram webhook updates"""
    if not bot_instance:
        logger.error("Bot not initialized")
        raise HTTPException(status_code=500, detail="Bot not initialized")

    try:
        # Get the request body
        body = await request.body()
        update_data = json.loads(body.decode("utf-8"))

        # Process the update
        update = Update.de_json(update_data, bot_instance.application.bot)
        await bot_instance.application.process_update(update)

        return Response(status_code=200)

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/set_webhook")
async def set_webhook(request: Request):
    """Set the webhook for the Telegram bot"""
    if not bot_instance:
        raise HTTPException(status_code=500, detail="Bot not initialized")

    try:
        # Get webhook URL from request or use default
        data = await request.json()
        webhook_url = data.get("webhook_url")

        if not webhook_url:
            # Try to get from environment
            webhook_url = os.getenv("WEBHOOK_URL")
            if not webhook_url:
                raise HTTPException(
                    status_code=400,
                    detail="webhook_url required in request body or WEBHOOK_URL environment variable",
                )

        # Set the webhook
        await bot_instance.application.bot.set_webhook(url=webhook_url)

        logger.info(f"Webhook set to: {webhook_url}")
        return {"status": "success", "webhook_url": webhook_url}

    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        raise HTTPException(status_code=500, detail="Failed to set webhook")


@app.delete("/webhook")
async def delete_webhook():
    """Delete the webhook (return to polling mode)"""
    if not bot_instance:
        raise HTTPException(status_code=500, detail="Bot not initialized")

    try:
        await bot_instance.application.bot.delete_webhook()
        logger.info("Webhook deleted")
        return {"status": "success", "message": "Webhook deleted"}

    except Exception as e:
        logger.error(f"Error deleting webhook: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete webhook")


if __name__ == "__main__":
    import uvicorn

    # Get port from environment (Render uses PORT)
    port = int(os.getenv("PORT", 8080))

    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
