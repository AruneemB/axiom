"""One-time script to register the Telegram webhook."""
import argparse
from lib.telegram_client import register_webhook


def main():
    parser = argparse.ArgumentParser(description="Register Telegram webhook")
    parser.add_argument("--bot-token", required=True, help="Telegram bot token")
    parser.add_argument("--webhook-url", required=True, help="Webhook URL")
    parser.add_argument("--secret", required=True, help="Webhook secret token")
    args = parser.parse_args()

    result = register_webhook(
        bot_token=args.bot_token,
        webhook_url=args.webhook_url,
        secret=args.secret,
    )
    print(result)


if __name__ == "__main__":
    main()
