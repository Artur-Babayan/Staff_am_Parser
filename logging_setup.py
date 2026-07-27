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


def register_user_if_new(update: Update):
    """
    Auto-registers any new chat_id on first contact, storing basic Telegram
    profile info (username, first name, language). New users start with
    an empty filter list - they add their own keywords via the bot.
    Existing users get their profile info refreshed in case it changed.
    """
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
    added, filters_list = db.add_filter(chat_id, keyword)

    if added:
        text = f"Filter '{keyword}' added.\n\n{format_filters_list(filters_list)}"
    else:
        text = f"Filter '{keyword}' is already in your list."

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
    added, filters_list = db.add_filter(chat_id, keyword)

    if added:
        text = f"Filter '{keyword}' added.\n\n{format_filters_list(filters_list)}"
    else:
        text = f"Filter '{keyword}' is already in your list."

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


async def on_remove_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    register_user_if_new(update)

    filters_list = db.load_filters(chat_id)

    if not filters_list:
        await query.edit_message_text(
            "Your filter list is empty, nothing to remove.", reply_markup=main_menu_keyboard()
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
    chat_id = update.effective_chat.id

    keyword = query.data.split(":", 1)[1]
    removed, filters_list = db.remove_filter(chat_id, keyword)

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