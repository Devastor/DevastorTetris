import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import InputFile
from PIL import Image, ImageDraw
import numpy as np
import io
import random
import sqlite3
import logging
import os
from concurrent.futures import ThreadPoolExecutor
# Инициализация бота и диспетчера
bot_token = ''
bot = Bot(token=bot_token)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)
dp.middleware.setup(LoggingMiddleware())
db_file = 'Devastor_TG_TETRIS_BD.db'
executor = ThreadPoolExecutor()
if not os.path.exists(db_file):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            current_index INTEGER DEFAULT 0,
            current_figure TEXT,
            current_x INTEGER DEFAULT 0,
            current_y INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
else:
    conn = sqlite3.connect(db_file)

cursor = conn.cursor()

# Параметры клеточного поля
grid_size = 10
cell_size = 40

# Определим начальный цвет клеток
cell_color_start = (255, 255, 255)
cell_colors = np.full((grid_size, grid_size, 3), cell_color_start, dtype=np.uint8)

# Глобальные переменные для текущей фигуры
current_figure_x = 0
current_figure_y = 0
current_tetris_figure = None
user_chat_id = {}  # Добавляем словарь для хранения чата по user_id
falling = False

@dp.message_handler(commands=['start'])
async def on_start(message: types.Message):
    user_id = message.from_user.id
    user_chat_id[user_id] = message.chat.id
    asyncio.create_task(create_initial_figure(user_id, message.chat.id))
    await message.reply("Добро пожаловать в игру! Выберите действие:", reply_markup=get_keyboard(user_id))
    logging.info(f"User {user_id} started the game.")

# Добавим логирование для создания начальной фигуры
async def create_initial_figure(user_id, chat_id):
    global current_figure_x, current_figure_y, current_tetris_figure
    current_tetris_figure, vertical_offset = generate_tetris_figure()
    current_figure_x = grid_size // 2 - len(current_tetris_figure[0]) // 2
    current_figure_y = 1  # Измените это значение, чтобы фигура появилась в верхней части стикера
    await update_grid(user_id, chat_id, current_tetris_figure)
    logging.info(f"Initial figure created for user {user_id}. Coordinates: x={current_figure_x}, y={current_figure_y}.")

def handle_bottom_collision_sync(user_id, chat_id, tetris_figure):
    global current_figure_x, current_figure_y, falling

    current_figure_y -= 1  # Возвращаем фигуру на одну клетку назад
    print(">>> update_current_position")
    update_current_position(current_figure_x, current_figure_y, tetris_figure)

    # Здесь можно добавить код для проверки заполненных рядов и их удаления
    print(">>> check_and_remove_rows")
    check_and_remove_rows()

    # Генерируем новую случайную фигуру и помещаем ее в центр
    print(">>> generate_tetris_figure")
    current_tetris_figure, _ = generate_tetris_figure()
    current_figure_x = grid_size // 2 - len(current_tetris_figure[0]) // 2
    current_figure_y = 1  # Измените это значение, чтобы фигура появилась в верхней части стикера
    falling = False  # Сбрасываем статус падения

    print(">>> ensure_future (update_grid)")
    asyncio.ensure_future(update_grid(user_id, chat_id, current_tetris_figure))  # Вызываем асинхронную функцию

async def handle_bottom_collision(user_id, chat_id, tetris_figure):
    global current_figure_x, current_figure_y, falling

    current_figure_y -= 1  # Возвращаем фигуру на одну клетку назад
    update_current_position(current_figure_x, current_figure_y, tetris_figure)

    # Здесь можно добавить код для проверки заполненных рядов и их удаления
    check_and_remove_rows()

    # Генерируем новую случайную фигуру и помещаем ее в центр
    current_tetris_figure, _ = generate_tetris_figure()
    current_figure_x = grid_size // 2 - len(current_tetris_figure[0]) // 2
    current_figure_y = 1  # Измените это значение, чтобы фигура появилась в верхней части стикера
    falling = False  # Сбрасываем статус падения

    await update_grid(user_id, chat_id, current_tetris_figure)

@dp.callback_query_handler(lambda query: query.data == 'rotate')
async def rotate_figure(query: types.CallbackQuery):
    user_id = query.from_user.id
    global current_tetris_figure, current_figure_x, current_figure_y

    old_tetris_figure = current_tetris_figure.copy()
    current_tetris_figure = np.transpose(current_tetris_figure[::-1, :])
    if not is_valid_position(current_figure_x, current_figure_y, current_tetris_figure):
        current_tetris_figure = old_tetris_figure
        return

    await update_grid(user_id, query.message.chat.id, current_tetris_figure)
    # Вызываем асинхронную функцию handle_bottom_collision_sync в потоке пула
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(executor, handle_bottom_collision_sync, user_id, query.message.chat.id, current_tetris_figure)

@dp.callback_query_handler(lambda query: query.data == 'left')
async def move_left(query: types.CallbackQuery):
    user_id = query.from_user.id
    global current_figure_x
    global current_figure_y
    current_figure_x -= 1
    if current_figure_x < 0:
        current_figure_x = 0
    await update_grid(user_id, query.message.chat.id, current_tetris_figure)
    # Вызываем асинхронную функцию handle_bottom_collision_sync в потоке пула
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(executor, handle_bottom_collision_sync, user_id, query.message.chat.id, current_tetris_figure)

@dp.callback_query_handler(lambda query: query.data == 'right')
async def move_right(query: types.CallbackQuery):
    user_id = query.from_user.id
    global current_figure_x
    global current_figure_y
    current_figure_x += 1
    if current_figure_x + len(current_tetris_figure[0]) > grid_size:
        current_figure_x = grid_size - len(current_tetris_figure[0])
    await update_grid(user_id, query.message.chat.id, current_tetris_figure)
    # Вызываем асинхронную функцию handle_bottom_collision_sync в потоке пула
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(executor, handle_bottom_collision_sync, user_id, query.message.chat.id, current_tetris_figure)

def calculate_figure_position(figure):
    x = (grid_size - figure.shape[1]) // 2
    y = 0
    return x, y

def generate_tetris_figure():
    """
    Генерирует случайную фигуру тетриса.

    Возвращает матрицу, представляющую фигуру, где 1 - заполненная клетка, 0 - пустая, и вертикальное смещение.

    :return: Матрица фигуры и вертикальное смещение
    """
    # Список предопределенных фигур в виде матриц 4x4
    tetris_figures = [
        (np.array([[1, 1, 1, 1],
                    [0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0, 0]], dtype=np.uint8), 0),  # Фигура "I"

        (np.array([[1, 1, 0, 0],
                    [1, 1, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0, 0]], dtype=np.uint8), 0),  # Фигура "O"

        (np.array([[0, 1, 0, 0],
                    [1, 1, 1, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0, 0]], dtype=np.uint8), 0),  # Фигура "T"

        (np.array([[1, 0, 0, 0],
                    [1, 1, 1, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0, 0]], dtype=np.uint8), 0),  # Фигура "L"

        (np.array([[0, 0, 1, 0],
                    [1, 1, 1, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0, 0]], dtype=np.uint8), 0),  # Фигура "J"

        (np.array([[0, 1, 1, 0],
                    [1, 1, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0, 0]], dtype=np.uint8), 0),  # Фигура "S"

        (np.array([[1, 1, 0, 0],
                    [0, 1, 1, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0, 0]], dtype=np.uint8), 0)  # Фигура "Z"
    ]

    # Выбираем случайную фигуру из списка
    random_figure, vertical_offset = random.choice(tetris_figures)

    return random_figure, vertical_offset

def is_valid_position(x, y, figure):
    for row in range(figure.shape[0]):
        for col in range(figure.shape[1]):
            if figure[row, col] == 1:
                if (
                    x + col < 0
                    or x + col + 1 >= grid_size
                    or y + row >= grid_size
                    or cell_colors[y + row, x + col].any()
                ):
                    return False
    return True

# Функция для обновления клеток, где фигура была ранее
def update_previous_position(x, y, figure):
    for row in range(figure.shape[0]):
        for col in range(figure.shape[1]):
            if figure[row, col] == 1:
                cell_colors[y + row, x + col] = cell_color_start

# Функция для обновления клеток, где фигура должна быть сейчас
def update_current_position(x, y, figure):
    for row in range(figure.shape[0]):
        for col in range(figure.shape[1]):
            if figure[row, col] == 1:
                cell_colors[y + row, x + col] = (0, 255, 0)

def update_cell_colors(x, y, figure):
    for row in range(figure.shape[0]):
        for col in range(figure.shape[1]):
            if figure[row, col] == 1:
                cell_colors[y + row, x + col] = (0, 255, 0)

def generate_sticker_with_figure(index, tetris_figure, current_figure_x, current_figure_y):
    image = Image.new('RGB', (grid_size * cell_size, grid_size * cell_size), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)

    for x in range(grid_size):
        for y in range(grid_size):
            color = tuple(cell_colors[x, y])
            draw.rectangle([(x * cell_size, y * cell_size), ((x + 1) * cell_size, (y + 1) * cell_size)],
                           fill=color, outline=(0, 0, 0))

    for x in range(grid_size):
        draw.line([(x * cell_size, 0), (x * cell_size, grid_size * cell_size)], fill=(0, 0, 0), width=2)
    for y in range(grid_size):
        draw.line([(0, y * cell_size), (grid_size * cell_size, y * cell_size)], fill=(0, 0, 0), width=2)

    figure_coordinates = get_figure_coordinates(tetris_figure, current_figure_x, current_figure_y)

    for x, y in figure_coordinates:
        draw.rectangle([(x * cell_size, y * cell_size), ((x + 1) * cell_size, (y + 1) * cell_size)],
                       fill=(0, 255, 0), outline=(255, 255, 255))
        
        # Отладочный вывод координат фигуры
        print(f"Figure coordinate: x={x}, y={y}")

    sticker_data = io.BytesIO()
    try:
        image.save(sticker_data, 'PNG')
    except e:        
        print(f"EERROR:", e)
    sticker_data.seek(0)
    return sticker_data

def get_figure_coordinates(figure, x, y):
    coordinates = []
    for j in range(len(figure)):
        for i in range(len(figure[j])):
            if figure[j, i] == 1:
                coordinates.append((i + x, j + y))
    return coordinates

# Изменения в функции get_keyboard
def get_keyboard(user_id, can_move_left=True, can_move_right=True):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="⬆️", callback_data="rotate"))
    
    if can_move_left:
        keyboard.add(types.InlineKeyboardButton(text="⬅️", callback_data="left"))
    
    if can_move_right:
        keyboard.add(types.InlineKeyboardButton(text="➡️", callback_data="right"))

    return keyboard

# Функция для проверки и удаления заполненных рядов
def check_and_remove_rows():
    global cell_colors

    # Перебираем строки снизу вверх
    for row in reversed(range(grid_size)):
        if np.all(cell_colors[row, :] == (0, 255, 0)):  # Если строка полностью заполнена
            cell_colors[1:row + 1, :] = cell_colors[:row, :]  # Сдвигаем все строки выше на одну вниз
            cell_colors[0, :] = cell_color_start  # Заполняем верхнюю строку пустыми клетками


# Функция для получения текущего индекса пользователя из базы данных
def get_current_index(user_id):
    cursor.execute('SELECT current_index FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

# Функция для обновления текущего индекса пользователя в базе данных
def update_current_index(user_id, index):
    cursor.execute('INSERT OR REPLACE INTO users (user_id, current_index) VALUES (?, ?)', (user_id, index))
    conn.commit()

# Изменения в функции update_grid для управления фигурой
async def update_grid(user_id, chat_id, tetris_figure):
    print(">>> updating grid...")
    global current_figure_x, current_figure_y, falling

    current_index = get_current_index(user_id)
    sticker_data = generate_sticker_with_figure(current_index, tetris_figure, current_figure_x, current_figure_y)


    update_previous_position(current_figure_x, current_figure_y, tetris_figure)
    current_figure_y += 1
    update_current_position(current_figure_x, current_figure_y, tetris_figure)
    can_move_left = True
    can_move_right = True
    """
    if not is_valid_position(current_figure_x, current_figure_y + 1, tetris_figure):
        falling = False  # Если фигура достигла нижней границы, устанавливаем статус в "не падает"
        await asyncio.sleep(1)  # Добавляем задержку после достижения нижней границы
        await handle_bottom_collision(user_id, chat_id, tetris_figure)  # Обработка столкновения снизу
        return
        """
    if current_index == get_current_index(user_id):
        await bot.send_sticker(chat_id, InputFile(sticker_data))
        await bot.send_message(chat_id, "Выберите действие:", reply_markup=get_keyboard(user_id, can_move_left=can_move_left, can_move_right=can_move_right))
        logging.info(f"Sticker sent to user {user_id}. Coordinates: x={current_figure_x}, y={current_figure_y}.")


if __name__ == '__main__':
    from aiogram import executor
    executor.start_polling(dp)




