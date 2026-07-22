import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

from filters_store import load_filters, add_filter, remove_filter
from keyboards import main_menu_keyboard, CB_FILTERS, CB_ADD, CB_REMOVE

load_dotenv()

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_FOR_NEW_FILTER = 1


def is_authorized(update: Update) -> bool:
    if not CHAT_ID:
        return True
    chat_id = update.effective_chat.id if update.effective_chat else None
    return str(chat_id) == str(CHAT_ID)


def format_filters_list(filters_list: list) -> str:
    if not filters_list:
        return "Filter list is empty."
    return "Current filters:\n" + "\n".join(f"• {f}" for f in filters_list)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Hi! I'm the filter bot for the staff.am job parser.\n\n"
        "Use the buttons below, or these commands:\n"
        "/filters - show current filters\n"
        "/add <word> - add a filter, e.g.: /add QA\n"
        "/remove <word> - remove a filter, e.g.: /remove Django"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def filters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("You don't have access to this bot.")
        return

    await update.message.reply_text(
        format_filters_list(load_filters()), reply_markup=main_menu_keyboard()
    )


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("You don't have access to this bot.")
        return

    if not context.args:
        await update.message.reply_text("Specify a keyword, e.g.: /add QA")
        return

    keyword = " ".join(context.args)
    added, filters_list = add_filter(keyword)

    if added:
        text = f"Filter '{keyword}' added.\n\n{format_filters_list(filters_list)}"
    else:
        text = f"Filter '{keyword}' is already in the list."

    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("You don't have access to this bot.")
        return

    if not context.args:
        await update.message.reply_text("Specify a keyword, e.g.: /remove Django")
        return

    keyword = " ".join(context.args)
    removed, filters_list = remove_filter(keyword)

    if removed:
        text = f"Filter '{keyword}' removed.\n\n{format_filters_list(filters_list)}"
    else:
        text = f"Filter '{keyword}' not found in the list."

    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def on_filters_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        await query.edit_message_text("You don't have access to this bot.")
        return

    await query.edit_message_text(
        format_filters_list(load_filters()), reply_markup=main_menu_keyboard()
    )


async def on_add_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        await query.edit_message_text("You don't have access to this bot.")
        return ConversationHandler.END

    context.user_data["menu_chat_id"] = query.message.chat_id
    context.user_data["menu_message_id"] = query.message.message_id

    await query.edit_message_text(
        "Enter the keyword you want to add to the filters (e.g.: QA):"
    )
    return WAITING_FOR_NEW_FILTER


async def on_new_filter_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.strip()
    added, filters_list = add_filter(keyword)

    if added:
        text = f"Filter '{keyword}' added.\n\n{format_filters_list(filters_list)}"
    else:
        text = f"Filter '{keyword}' is already in the list."

    chat_id = context.user_data.get("menu_chat_id")
    message_id = context.user_data.get("menu_message_id")

    if chat_id and message_id:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())

    try:
        await update.message.delete()
    except Exception:
        pass

    return ConversationHandler.END


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def on_remove_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        await query.edit_message_text("You don't have access to this bot.")
        return

    filters_list = load_filters()

    if not filters_list:
        await query.edit_message_text(
            "Filter list is empty, nothing to remove.", reply_markup=main_menu_keyboard()
        )
        return

    keyboard = [
        [InlineKeyboardButton(f"🗑 {f}", callback_data=f"remove_filter:{f}")]
        for f in filters_list
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=CB_FILTERS)])

    await query.edit_message_text(
        "Choose which filter to remove:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def on_remove_filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized(update):
        await query.edit_message_text("You don't have access to this bot.")
        return

    keyword = query.data.split(":", 1)[1]
    removed, filters_list = remove_filter(keyword)

    if removed:
        text = f"Filter '{keyword}' removed.\n\n{format_filters_list(filters_list)}"
    else:
        text = f"Filter '{keyword}' was already removed."

    await query.edit_message_text(text, reply_markup=main_menu_keyboard())


def main():
    if not TOKEN:
        raise RuntimeError("TOKEN not found in .env file.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("filters", filters_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("remove", remove_command))

    add_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(on_add_button, pattern=f"^{CB_ADD}$")],
        states={
            WAITING_FOR_NEW_FILTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_new_filter_text)
            ],
        },
        fallbacks=[CommandHandler("cancel", on_cancel)],
    )
    app.add_handler(add_conversation)

    app.add_handler(CallbackQueryHandler(on_filters_button, pattern=f"^{CB_FILTERS}$"))
    app.add_handler(CallbackQueryHandler(on_remove_button, pattern=f"^{CB_REMOVE}$"))
    app.add_handler(CallbackQueryHandler(on_remove_filter_callback, pattern=r"^remove_filter:"))

    logger.info("Bot started and listening for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()