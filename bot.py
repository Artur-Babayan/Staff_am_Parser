import os
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

import db
from keyboards import main_menu_keyboard, CB_FILTERS, CB_ADD, CB_REMOVE
from logging_setup import get_logger

load_dotenv()

TOKEN = os.getenv("TOKEN")

logger = get_logger(__name__, "bot.log")

WAITING_FOR_NEW_FILTER = 1


def format_filters_list(filters_list: list) -> str:
    if not filters_list:
        return "Your filter list is empty."
    return "Your current filters:\n" + "\n".join(f"• {f}" for f in filters_list)


def format_add_filter_result(status: str, keyword: str, filters_list: list) -> str:
    if status == "added":
        return f"Filter '{keyword.strip()}' added.\n\n{format_filters_list(filters_list)}"
    if status == "empty":
        return "Filter cannot be empty."
    if status == "too_long":
        return f"Filter is too long. Maximum length is {db.MAX_FILTER_LENGTH} characters."
    if status == "limit":
        return f"You can have at most {db.MAX_FILTERS_PER_USER} filters."
    return f"Filter '{keyword.strip()}' is already in your list."


def register_user_if_new(update: Update):
    chat_id = update.effective_chat.id
    user = update.effective_user

    is_new = db.ensure_user(
        chat_id,
        username=user.username if user else None,
        first_name=user.first_name if user else None,
        language_code=user.language_code if user else None,
    )
    if is_new:
        logger.info(f"New user registered: {chat_id} (@{user.username if user else 'unknown'})")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    register_user_if_new(update)

    text = (
        "Hi! I'm the filter bot for the staff.am job parser.\n\n"
        "These filters are personal to you - other users don't see your "
        "filters or your job notifications, and you don't see theirs.\n\n"
        "Your filter list is currently empty - use 'Add' below to add "
        "keywords you're interested in (e.g. Python, QA, DevOps).\n\n"
        "Use the buttons below, or these commands:\n"
        "/filters - show your current filters\n"
        "/add <word> - add a filter, e.g.: /add QA\n"
        "/remove <word> - remove a filter, e.g.: /remove Django"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def filters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    register_user_if_new(update)

    await update.message.reply_text(
        format_filters_list(db.load_filters(chat_id)), reply_markup=main_menu_keyboard()
    )


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    register_user_if_new(update)

    if not context.args:
        await update.message.reply_text("Specify a keyword, e.g.: /add QA")
        return

    keyword = " ".join(context.args)
    status, filters_list = db.add_filter(chat_id, keyword)
    text = format_add_filter_result(status, keyword, filters_list)

    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    register_user_if_new(update)

    if not context.args:
        await update.message.reply_text("Specify a keyword, e.g.: /remove Django")
        return

    keyword = " ".join(context.args)
    removed, filters_list = db.remove_filter(chat_id, keyword)

    if removed:
        text = f"Filter '{keyword}' removed.\n\n{format_filters_list(filters_list)}"
    else:
        text = f"Filter '{keyword}' not found in your list."

    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def on_filters_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    register_user_if_new(update)

    await query.edit_message_text(
        format_filters_list(db.load_filters(chat_id)), reply_markup=main_menu_keyboard()
    )


async def on_add_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    register_user_if_new(update)

    context.user_data["menu_chat_id"] = query.message.chat_id
    context.user_data["menu_message_id"] = query.message.message_id

    await query.edit_message_text(
        "Enter the keyword you want to add to your filters (e.g.: QA):"
    )
    return WAITING_FOR_NEW_FILTER


async def on_new_filter_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    keyword = update.message.text.strip()
    status, filters_list = db.add_filter(chat_id, keyword)
    text = format_add_filter_result(status, keyword, filters_list)

    menu_chat_id = context.user_data.get("menu_chat_id")
    menu_message_id = context.user_data.get("menu_message_id")

    if menu_chat_id and menu_message_id:
        await context.bot.edit_message_text(
            chat_id=menu_chat_id,
            message_id=menu_message_id,
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


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    logger.error(
        "Unhandled bot update error",
        exc_info=(type(error), error, error.__traceback__),
    )


async def on_remove_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    register_user_if_new(update)

    filter_records = db.load_filter_records(chat_id)

    if not filter_records:
        await query.edit_message_text(
            "Your filter list is empty, nothing to remove.", reply_markup=main_menu_keyboard()
        )
        return

    keyboard = [
        [InlineKeyboardButton(f"🗑 {record['keyword']}", callback_data=f"remove_filter:{record['id']}")]
        for record in filter_records
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=CB_FILTERS)])

    await query.edit_message_text(
        "Choose which filter to remove:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def on_remove_filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    raw_filter_id = query.data.split(":", 1)[1]
    try:
        filter_id = int(raw_filter_id)
    except ValueError:
        await query.edit_message_text(
            "This button is outdated. Open the filter list again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    removed, keyword, filters_list = db.remove_filter_by_id(chat_id, filter_id)
    if removed:
        text = f"Filter '{keyword}' removed.\n\n{format_filters_list(filters_list)}"
    else:
        text = "This filter was already removed."

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
    app.add_error_handler(on_error)

    logger.info("Bot started and listening for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()