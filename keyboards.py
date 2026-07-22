from telegram import InlineKeyboardMarkup, InlineKeyboardButton

CB_FILTERS = "menu:filters"
CB_ADD = "menu:add"
CB_REMOVE = "menu:remove"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("📋 Filters", callback_data=CB_FILTERS),
            InlineKeyboardButton("➕ Add", callback_data=CB_ADD),
            InlineKeyboardButton("➖ Remove", callback_data=CB_REMOVE),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)