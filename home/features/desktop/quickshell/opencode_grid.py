"""Character-cell layout shared by the popup and its Kitty rasterizer."""
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


COLUMNS = 70
HEADER_ROWS = 3
SESSION_ROWS = 4
FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
BACKGROUND = "#0d1117"
FOREGROUND = "#c9d1d9"
MUTED = "#8b949e"
BORDER = "#484f58"
SELECTION = "#161b22"


def clean(text):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(text))


def width(character):
    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in ("W", "F") else 1


def take(text, columns):
    """Split on cell boundaries, preserving combining marks and wide glyphs."""
    used = 0
    for index, character in enumerate(text):
        size = width(character)
        if used + size > columns:
            return text[:index], text[index:]
        used += size
    return text, ""


@dataclass
class Cell:
    text: str = " "
    color: str = FOREGROUND
    bold: bool = False
    background: str = BACKGROUND


class Grid:
    def __init__(self, columns, rows):
        self.columns, self.rows = columns, rows
        self.cells = [[Cell() for _ in range(columns)] for _ in range(rows)]

    def put(self, column, row, text, color=FOREGROUND, bold=False):
        if not 0 <= row < self.rows:
            return
        for character in clean(text):
            size = width(character)
            if not size:
                if column > 0:
                    previous = column - 1
                    while previous > 0 and self.cells[row][previous].text == "":
                        previous -= 1
                    self.cells[row][previous].text += character
                continue
            if column < 0 or column + size > self.columns:
                return
            self.cells[row][column].text = character
            self.cells[row][column].color = color
            self.cells[row][column].bold = bold
            for continuation in range(1, size):
                self.cells[row][column + continuation].text = ""
            column += size

    def paint(self, start_row, end_row, color):
        for row in self.cells[start_row:end_row]:
            for cell in row[1:-1]:
                cell.background = color

def context_name(session, catalog):
    for node in catalog.get("nodes", []):
        name = session.get("tmux_name", "")
        if name == "context-" + node["id"] or (node.get("runtime_id") and name.endswith("-" + node["runtime_id"])):
            return node.get("breadcrumb") or node.get("label", name)
    return Path(session.get("directory", "")).name or session.get("tmux_name", "")


def status(session):
    return {"input": "Needs input", "error": "Session failed", "done": "Finished", "idle": "Idle"}.get(
        session["state"], {"retry": "Retrying…", "plan": "Planning…"}.get(session["mode"], "Working…"))


def visible_count(rows):
    return max(1, (rows - HEADER_ROWS - 1) // SESSION_ROWS)


def compose(sessions, catalog, columns, rows, frame, offset=0, selected=-1, error="", character_border=True):
    grid = Grid(columns, rows)
    grid.put(0, 0, "┌" + "─" * (columns - 2) + "┐", BORDER)
    grid.put(0, 2, "├" + "─" * (columns - 2) + "┤", BORDER)
    grid.put(0, rows - 1, "└" + "─" * (columns - 2) + "┘", BORDER)
    for row in range(1, rows - 1):
        if row == 2:
            continue
        grid.put(0, row, "│", BORDER)
        grid.put(columns - 1, row, "│", BORDER)
    if character_border:
        grid.put((columns - 8) // 2, 1, "opencode", FOREGROUND, True)
    text_columns = max(1, columns - 8)
    for index, session in enumerate(sessions[offset:offset + visible_count(rows)], offset):
        row = HEADER_ROWS + (index - offset) * SESSION_ROWS
        if index == selected:
            grid.paint(row, min(row + SESSION_ROWS - 1, rows - 1), SELECTION)
        icon = FRAMES[frame % len(FRAMES)] if session["state"] == "working" else session.get("icon") or "·"
        grid.put(2, row, icon, session["color"])
        title, rest = take(clean(session["title"]), text_columns)
        grid.put(4, row, title, FOREGROUND, True)
        if rest:
            title, rest = take(rest, text_columns)
            if rest:
                title, _ = take(title, text_columns - 1)
                title += "…"
            grid.put(4, row + 1, title, FOREGROUND, True)
        description, rest = take(clean(context_name(session, catalog) + " · " + status(session)), text_columns)
        if rest:
            description, _ = take(description, text_columns - 1)
            description += "…"
        grid.put(4, row + 2, description, MUTED)
        grid.put(columns - 3, row, ">", MUTED)
    if not sessions or error:
        grid.put(4, HEADER_ROWS, take(clean(error or "No OpenCode sessions open"), text_columns)[0], MUTED)
    if offset:
        grid.put(columns - 3, 2, "↑", MUTED)
    if offset + visible_count(rows) < len(sessions):
        grid.put(columns - 3, rows - 1, "↓", MUTED)
    if not character_border:
        # The popup draws its real rounded 2px window border. Keep terminal
        # cells as padding instead of drawing a second, square character box.
        for row in (0, rows - 1):
            for cell in grid.cells[row]:
                if cell.text in "┌┐└┘─│":
                    cell.text = " "
        for row in grid.cells:
            row[0].text = row[-1].text = " "
    return grid
