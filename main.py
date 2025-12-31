import os
import sys
import shutil
import json
import time
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QTextEdit, QFileDialog, QMessageBox,
    QFrame, QSplashScreen
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QSize, QUrl, QEvent
from PySide6.QtGui import QPixmap, QIcon, QAction, QDesktopServices

try:
    from PySide6.QtMultimedia import QSoundEffect
    SOUND_AVAILABLE = True
except Exception:
    SOUND_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except Exception:
    REQUESTS_AVAILABLE = False

# ---------------------------------------------------------
# CONSTANTS / PATHS
# ---------------------------------------------------------

CONFIG_FILE = "config.json"
LOGS_DIR = "logs"
BACKUP_DIR = "Backups"

MSC_LOADER_LOCAL_ZIP = "MSC_Loader_1.3.4.zip"

APP_NAME = "My Winter Car Fix"


# ---------------------------------------------------------
# CONFIG + LOGGING
# ---------------------------------------------------------

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {
            "runs": 0,
            "last_path": "",
            "last_action": "None",
            "last_launch": "Never"
        }
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "runs": 0,
            "last_path": "",
            "last_action": "None",
            "last_launch": "Never"
        }


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print("Config save error:", e)


def write_log_line(text: str):
    os.makedirs(LOGS_DIR, exist_ok=True)
    filename = datetime.now().strftime("%Y-%m-%d.log")
    path = os.path.join(LOGS_DIR, filename)
    with open(path, "a", encoding="utf-8") as f:
        ts = datetime.now().strftime("%H:%M:%S")
        f.write(f"[{ts}] {text}\n")


# ---------------------------------------------------------
# SHORTCUT
# ---------------------------------------------------------

def create_shortcut(target_path: Path, shortcut_name="My Winter Car Fix.lnk"):
    try:
        import win32com.client
        desktop = Path(os.path.join(os.environ["USERPROFILE"], "Desktop"))
        shortcut_path = desktop / shortcut_name

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(shortcut_path))
        shortcut.TargetPath = str(target_path)
        shortcut.WorkingDirectory = str(target_path.parent)
        shortcut.IconLocation = str(target_path)
        shortcut.save()
        return True
    except Exception as e:
        print("Shortcut error:", e)
        write_log_line(f"Shortcut error: {e}")
        return False


# ---------------------------------------------------------
# GAME DETECTION
# ---------------------------------------------------------

def looks_like_mwc_folder(path: Path) -> bool:
    exe_mwc = path / "mywintercar.exe"
    exe_msc = path / "mysummercar.exe"
    data_mwc = path / "mywintercar_Data"
    data_msc = path / "mysummercar_Data"

    if exe_mwc.exists() and data_mwc.exists():
        return True
    if exe_msc.exists() and data_msc.exists():
        return True
    return False


from concurrent.futures import ThreadPoolExecutor, as_completed


def find_mwc_candidates() -> list[Path]:
    candidates: list[Path] = []
    checked = set()

    BAD_DIRS = {
        "windows", "programdata", "system volume information",
        "$recycle.bin", "recycler", "recovery", "tmp", "temp"
    }

    TARGET_NAMES = {
        "my winter car",
        "winter",
        "mysummercar",
        "mywintercar"
    }

    def fast_check(path: Path):
        try:
            if path in checked:
                return None
            checked.add(path)

            name = path.name.lower()
            if any(x in name for x in TARGET_NAMES):
                if looks_like_mwc_folder(path):
                    return path

            for obj in os.scandir(path):
                if not obj.is_dir():
                    continue

                low = obj.name.lower()

                if low in BAD_DIRS:
                    continue

                p = Path(obj.path)

                if (p / "mywintercar.exe").exists() or (p / "mysummercar.exe").exists():
                    if looks_like_mwc_folder(p):
                        return p

        except Exception:
            return None

        return None

    drives = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        d = Path(f"{letter}:\\")
        if d.exists():
            drives.append(d)

    fast_paths = [
        Path("C:/Program Files (x86)/Steam/steamapps/common"),
        Path("C:/Program Files/Steam/steamapps/common"),
        Path("D:/SteamLibrary/steamapps/common"),
        Path("E:/SteamLibrary/steamapps/common"),
    ]

    for p in fast_paths:
        if p.exists() and p not in drives:
            drives.append(p)

    with ThreadPoolExecutor(max_workers=12) as exe:
        futures = []
        for root in drives:
            try:
                for entry in os.scandir(root):
                    if entry.is_dir():
                        futures.append(exe.submit(fast_check, Path(entry.path)))
            except Exception:
                pass

        for f in as_completed(futures):
            res = f.result()
            if res and res not in candidates:
                candidates.append(res)

    return candidates


# ---------------------------------------------------------
# BACKUP SYSTEM
# ---------------------------------------------------------

def create_backup(game_folder: Path) -> Path | None:
    try:
        if not game_folder.exists():
            return None
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_folder = Path(BACKUP_DIR) / f"MWC_Backup_{ts}"

        write_log_line(f"Creating backup at {backup_folder}")
        shutil.copytree(game_folder, backup_folder)
        return backup_folder
    except Exception as e:
        write_log_line(f"Backup error: {e}")
        return None


# ---------------------------------------------------------
# FMF HELPER FILES + COPY
# ---------------------------------------------------------

def ensure_fmf_useful_files():
    base = Path("fmf")
    base.mkdir(exist_ok=True)

    files_content = {
        "readme.txt": (
            "FMF FOLDER\n"
            "==========\n\n"
            "This folder is used by the My Winter Car → MSC Loader Fix tool.\n"
            "Place any extra DLL/EXE/config files here.\n"
            "They will be copied into the game folder after a successful FIX.\n"
        ),
        "fix_info.txt": (
            "FIX INFORMATION\n"
            "===============\n\n"
            "Game prepared for MSC Loader compatibility.\n"
            "Names usually changed:\n"
            "- mywintercar.exe  -> mysummercar.exe\n"
            "- mywintercar_Data -> mysummercar_Data\n"
        ),
        "license.txt": (
            "TOOL LICENSE / DISCLAIMER\n"
            "=========================\n\n"
            "This helper tool is provided \"as is\".\n"
            "- Use at your own risk.\n"
            "- Always keep a backup.\n"
        ),
        "support_info.txt": (
            "SUPPORT / TROUBLESHOOTING\n"
            "=========================\n\n"
            "If something goes wrong:\n"
            "- Check backup in Backups/ folder\n"
            "- Restore backup if needed\n"
            "- Verify correct game folder\n"
        )
    }

    for name, content in files_content.items():
        path = base / name
        if not path.exists():
            try:
                path.write_text(content, encoding="utf-8")
                write_log_line(f"Created FMF helper file: {path}")
            except Exception as e:
                write_log_line(f"FMF file create error {name}: {e}")


def copy_fmf_to_game(game_folder: Path) -> tuple[int, int]:
    """
    Копируем ВСЁ содержимое папки fmf в папку игры.
    Структура папок сохраняется, файлы перезаписываются.
    Возвращаем (кол-во файлов, кол-во папок).
    """
    base = Path("fmf")
    if not base.exists():
        write_log_line("FMF folder not found, nothing to copy.")
        return 0, 0

    copied_files = 0
    copied_dirs = 0

    for root, dirs, files in os.walk(base):
        root_path = Path(root)
        rel = root_path.relative_to(base)
        dest_dir = game_folder / rel
        dest_dir.mkdir(parents=True, exist_ok=True)

        if rel != Path("."):
            copied_dirs += 1

        for f in files:
            src = root_path / f
            dest = dest_dir / f
            try:
                shutil.copy2(src, dest)
                copied_files += 1
            except Exception as e:
                write_log_line(f"FMF copy error {src} -> {dest}: {e}")

    write_log_line(f"FMF copied: {copied_files} files, {copied_dirs} folders into {game_folder}")
    return copied_files, copied_dirs


# ---------------------------------------------------------
# MSC LOADER INSTALL
# ---------------------------------------------------------

def install_mscloader_from_zip(game_folder: Path) -> tuple[bool, str]:
    zip_path = Path(MSC_LOADER_LOCAL_ZIP)
    if not zip_path.exists():
        return False, f"Local zip '{MSC_LOADER_LOCAL_ZIP}' not found. Please download it first."

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(game_folder)
        write_log_line(f"MSC Loader extracted from {zip_path} into {game_folder}")
        return True, "MSC Loader 1.3.4 installed from local zip."
    except Exception as e:
        write_log_line(f"MSC Loader unzip error: {e}")
        return False, f"Unzip failed: {e}"


# ---------------------------------------------------------
# MAIN WINDOW
# ---------------------------------------------------------

class MWCFixerWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.cfg = load_config()
        self.cfg["runs"] = self.cfg.get("runs", 0) + 1
        self.cfg["last_launch"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_config(self.cfg)

        self.game_path: Path | None = None
        if self.cfg.get("last_path"):
            p = Path(self.cfg["last_path"])
            if p.exists():
                self.game_path = p

        self.click_sound = None
        self.error_sound = None

        self._drag_active = False
        self._drag_pos = None
        self._title_bar = None
        
        self.init_ui()
        self.start_fade_in()

        # Auto FMF helper files
        ensure_fmf_useful_files()

        # Auto detect game on first launch or when no path
        QTimer.singleShot(800, self.auto_detect_game_if_needed)

    # ---------------- UI / STYLE ----------------

    def init_ui(self):
        self.setWindowTitle(APP_NAME)

        # Кастомное окно: без рамки, без системных кнопок
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.resize(820, 540)
        self.setFixedSize(820, 540)  # фиксированный размер, нельзя ресайзить
        self.setWindowOpacity(0.0)  # для fade анимации

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---------- кастомный title bar ----------
        title_bar = QWidget()
        title_bar.setObjectName("titleBar")
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(10, 4, 10, 4)
        tb_layout.setSpacing(8)

        icon_label = QLabel()
        icon_path = Path("assets") / "logo.png"
        if icon_path.exists():
            pix = QPixmap(str(icon_path)).scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(pix)

        title_label = QLabel(APP_NAME)
        title_label.setObjectName("windowTitle")
        title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self.info_label = QLabel()
        self.info_label.setObjectName("infoLabel")
        self.update_info_label()

        # Кнопки в заголовке
        btn_logs = QPushButton("Logs")
        btn_logs.setObjectName("titleButton")
        btn_logs.clicked.connect(self.on_open_logs_clicked)

        btn_cfg = QPushButton("Config")
        btn_cfg.setObjectName("titleButton")
        btn_cfg.clicked.connect(self.on_open_config_clicked)

        btn_help = QPushButton("?")
        btn_help.setObjectName("titleButton")
        btn_help.clicked.connect(self.on_open_nexus_page)

        btn_close = QPushButton("✕")
        btn_close.setObjectName("closeButton")
        btn_close.setFixedWidth(32)
        btn_close.clicked.connect(self.close)

        tb_layout.addWidget(icon_label)
        tb_layout.addWidget(title_label)
        tb_layout.addStretch()
        tb_layout.addWidget(self.info_label)
        tb_layout.addSpacing(12)
        tb_layout.addWidget(btn_logs)
        tb_layout.addWidget(btn_cfg)
        tb_layout.addWidget(btn_help)
        tb_layout.addSpacing(4)
        tb_layout.addWidget(btn_close)

        self._title_bar = title_bar

        # ---------- основное содержимое ----------
        frame = QFrame()
        frame.setObjectName("mainFrame")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(16, 16, 16, 16)
        frame_layout.setSpacing(10)

        self.setStyleSheet("""
            QMainWindow {
                background-color: #050505;
            }
            #titleBar {
                background-color: #080808;
                border-bottom: 1px solid #222222;
            }
            QLabel#windowTitle {
                font-size: 14px;
                font-weight: 600;
                color: #f0f0f0;
            }
            QLabel#infoLabel {
                font-size: 11px;
                color: #888888;
            }
            QPushButton#titleButton {
                background-color: transparent;
                border: none;
                padding: 4px 8px;
                color: #bbbbbb;
                font-size: 11px;
            }
            QPushButton#titleButton:hover {
                background-color: #202020;
                border-radius: 6px;
                color: #ffffff;
            }
            QPushButton#closeButton {
                background-color: transparent;
                border: none;
                padding: 4px 0;
                color: #bbbbbb;
                font-size: 13px;
            }
            QPushButton#closeButton:hover {
                background-color: #c0392b;
                color: #ffffff;
                border-radius: 8px;
            }
            #mainFrame {
                background-color: rgba(15, 15, 15, 230);
                border-radius: 18px;
                border: 1px solid #333;
            }
            QLabel#titleLabel {
                font-size: 22px;
                font-weight: bold;
                color: #ffffff;
            }
            QLabel#subtitleLabel {
                font-size: 13px;
                color: #bbbbbb;
            }
            QLabel#pathLabel {
                font-size: 13px;
                color: #dddddd;
            }
            QPushButton {
                background-color: #262626;
                border-radius: 10px;
                padding: 8px 14px;
                border: 1px solid #3b3b3b;
                color: #f0f0f0;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #333333;
                border-color: #888888;
            }
            QPushButton:pressed {
                background-color: #181818;
            }
            QTextEdit {
                background-color: #101010;
                border-radius: 10px;
                border: 1px solid #2b2b2b;
                color: #00ff9c;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
        """)

        title = QLabel(APP_NAME)
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)

        self.path_label = QLabel()
        self.path_label.setObjectName("pathLabel")
        self.path_label.setAlignment(Qt.AlignCenter)
        self.update_path_label()

        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(8)

        self.btn_auto_detect = QPushButton("Auto Detect Game")
        self.btn_auto_detect.clicked.connect(self.on_auto_detect_clicked)

        self.btn_browse = QPushButton("Browse Folder...")
        self.btn_browse.clicked.connect(self.on_browse_clicked)

        self.btn_open_backups = QPushButton("Open Backups Folder")
        self.btn_open_backups.clicked.connect(self.on_open_backups_clicked)

        self.btn_open_game = QPushButton("Open Game Folder")
        self.btn_open_game.clicked.connect(self.on_open_game_clicked)

        btn_row1.addWidget(self.btn_auto_detect)
        btn_row1.addWidget(self.btn_browse)
        btn_row1.addWidget(self.btn_open_backups)
        btn_row1.addWidget(self.btn_open_game)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(8)

        self.btn_fix = QPushButton("Apply FIX")
        self.btn_fix.clicked.connect(self.on_fix_clicked)

        self.btn_revert = QPushButton("Revert")
        self.btn_revert.clicked.connect(self.on_revert_clicked)

        self.btn_install_msc = QPushButton("Install Loader")
        self.btn_install_msc.clicked.connect(self.on_install_msc_clicked)

        btn_row2.addWidget(self.btn_fix)
        btn_row2.addWidget(self.btn_revert)
        btn_row2.addWidget(self.btn_install_msc)

        self.log = QTextEdit()
        self.log.setReadOnly(True)

        frame_layout.addWidget(title)
        frame_layout.addSpacing(6)
        frame_layout.addWidget(self.path_label)
        frame_layout.addLayout(btn_row1)
        frame_layout.addLayout(btn_row2)
        frame_layout.addWidget(self.log)

        main_layout.addWidget(title_bar)
        main_layout.addWidget(frame)

        self.statusBar().showMessage("Ready.")

        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def start_fade_in(self):
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(600)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.anim.start()

    # ---------------- HELPERS ----------------

    def update_info_label(self):
        runs = self.cfg.get("runs", 1)
        last_action = self.cfg.get("last_action", "None")
        self.info_label.setText(f"Runs: {runs} • Last: {last_action}")

    def update_path_label(self):
        if self.game_path and self.game_path.exists():
            self.path_label.setText(f"Game Folder: {self.game_path}")
        else:
            self.path_label.setText("Game Folder: Not Selected")

    def log_msg(self, text: str, error: bool = False):
        if error:
            self.log.setStyleSheet(
                "background-color:#101010;border-radius:10px;"
                "border:1px solid #2b2b2b;color:#ff6b6b;"
                "font-family:Consolas;font-size:12px;"
            )

        else:
            self.log.setStyleSheet(
                "background-color:#101010;border-radius:10px;"
                "border:1px solid #2b2b2b;color:#00ff9c;"
                "font-family:Consolas;font-size:12px;"
            )
            

        self.log.append(text)
        write_log_line(text)
        self.statusBar().showMessage(text, 5000)

    # ---------------- DRAG WINDOW (easy drag) ----------------

    def eventFilter(self, obj, event):
        if obj is self._title_bar:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_active = True
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return True
            elif event.type() == QEvent.MouseMove and self._drag_active and (event.buttons() & Qt.LeftButton):
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()
                return True
            elif event.type() == QEvent.MouseButtonRelease:
                self._drag_active = False
                event.accept()
                return True
        return super().eventFilter(obj, event)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_active = True
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_active and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_active = False
        event.accept()

    # ---------------- GAME DETECTION ----------------

    def auto_detect_game_if_needed(self):
        if self.game_path and self.game_path.exists():
            return
        self.auto_detect_game(prompt_if_found=True)

    def auto_detect_game(self, prompt_if_found: bool = True):
        self.log_msg("Searching for My Winter Car installation...")
        candidates = find_mwc_candidates()
        if not candidates:
            self.log_msg("No automatic game folder detected.", error=True)
            return

        best = candidates[0]

        if prompt_if_found:
            answer = QMessageBox.question(
                self,
                "Game Found",
                f"My Winter Car seems to be here:\n\n{best}\n\nUse this folder?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                self.set_game_path(best)
                self.log_msg("Game folder selected by auto-detect.")
            else:
                self.on_browse_clicked()
        else:
            self.set_game_path(best)
            self.log_msg("Game folder set by auto-detect.")

    def set_game_path(self, path: Path):
        self.game_path = path
        self.cfg["last_path"] = str(path)
        save_config(self.cfg)
        self.update_path_label()

    # ---------------- BUTTON HANDLERS ----------------

    def on_auto_detect_clicked(self):
        
        self.auto_detect_game(prompt_if_found=True)

    def on_browse_clicked(self):
        
        folder = QFileDialog.getExistingDirectory(self, "Select My Winter Car Folder")
        if not folder:
            return
        p = Path(folder)
        if not looks_like_mwc_folder(p):
            self.log_msg("Selected folder does not look like My Winter Car.", error=True)
            QMessageBox.warning(
                self,
                "Warning",
                "Selected folder does not seem to contain My Winter Car / My Summer Car executable.",
            )
        self.set_game_path(p)
        self.log_msg("Folder selected manually.")

    def on_open_backups_clicked(self):
        
        backups = Path(BACKUP_DIR)
        backups.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(backups)))

    def on_open_game_clicked(self):
        if not self.game_path or not self.game_path.exists():
            QMessageBox.information(self, "Game Folder", "Game folder is not selected or does not exist.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.game_path)))

    def on_open_logs_clicked(self):
        logs = Path(LOGS_DIR)
        logs.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs)))

    def on_open_config_clicked(self):
        cfg_path = Path(CONFIG_FILE)
        if cfg_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(cfg_path)))
        else:
            QMessageBox.information(self, "Config", "config.json does not exist yet.")

    def on_open_nexus_page(self):
        url = "https://www.nexusmods.com/mysummercar/mods/147"
        QDesktopServices.openUrl(QUrl(url))

    # ---------------- FIX / REVERT / MSC INSTALL ----------------

    def on_fix_clicked(self):
        if not self.game_path:
            QMessageBox.warning(self, "No Folder", "Select or auto-detect game folder first.")
            self.log_msg("Fix aborted: no game folder selected.", error=True)
            return

        if not looks_like_mwc_folder(self.game_path):
            QMessageBox.warning(
                self,
                "Not Valid",
                "This folder does not look like My Winter Car / My Summer Car.",
            )
            self.log_msg("Fix aborted: folder not valid game folder.", error=True)
            return

        answer = QMessageBox.question(
            self,
            "Backup + Fix",
            "This will create a backup and then rename files.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.log_msg("Fix cancelled by user.")
            return

        self.log_msg("Creating backup before fix...")
        backup_folder = create_backup(self.game_path)
        if not backup_folder:
            QMessageBox.warning(self, "Backup Failed", "Backup could not be created. Aborting.")
            self.log_msg("Backup failed. Fix aborted.", error=True)
            return

        self.log_msg(f"Backup created at {backup_folder}")

        exe_mwc = self.game_path / "mywintercar.exe"
        data_mwc = self.game_path / "mywintercar_Data"
        exe_msc = self.game_path / "mysummercar.exe"
        data_msc = self.game_path / "mysummercar_Data"

        try:
            if exe_mwc.exists():
                exe_mwc.rename(exe_msc)
                self.log_msg("Renamed mywintercar.exe -> mysummercar.exe")
            if data_mwc.exists():
                data_mwc.rename(data_msc)
                self.log_msg("Renamed mywintercar_Data -> mysummercar_Data")
        except Exception as e:
            self.log_msg(f"Rename error: {e}", error=True)
            QMessageBox.critical(self, "Error", f"Rename failed:\n{e}")
            return

        created = create_shortcut(exe_msc)
        if created:
            self.log_msg("Desktop shortcut created.")
        else:
            self.log_msg("Failed to create desktop shortcut.", error=True)

        # КОПИРУЕМ ВСЁ ИЗ FMF В ПАПКУ ИГРЫ
        files_copied, dirs_copied = copy_fmf_to_game(self.game_path)
        if files_copied > 0:
            self.log_msg(f"Copied {files_copied} file(s) from FMF into game folder.")
        else:
            self.log_msg("FMF folder empty or not found, nothing extra copied.")

        self.cfg["last_action"] = "FIXED"
        save_config(self.cfg)
        self.update_info_label()

        QMessageBox.information(
            self,
            "Done",
            "Game successfully converted for MSC Loader.\n"
            "FMF content has been copied on top of the game folder.\n"
            "You can now install MSC Loader or use your mods.",
        )
        self.log_msg("Fix completed successfully.")

    def on_revert_clicked(self):
        if not self.game_path:
            QMessageBox.warning(self, "No Folder", "Select or auto-detect game folder first.")
            self.log_msg("Revert aborted: no game folder selected.", error=True)
            return

        exe_mwc = self.game_path / "mywintercar.exe"
        data_mwc = self.game_path / "mywintercar_Data"
        exe_msc = self.game_path / "mysummercar.exe"
        data_msc = self.game_path / "mysummercar_Data"

        answer = QMessageBox.question(
            self,
            "Revert",
            "This will try to rename mysummercar.exe -> mywintercar.exe and data folder back.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.log_msg("Revert cancelled by user.")
            return

        try:
            if exe_msc.exists():
                exe_msc.rename(exe_mwc)
                self.log_msg("Renamed mysummmercar.exe -> mywintercar.exe")
            if data_msc.exists():
                data_msc.rename(data_mwc)
                self.log_msg("Renamed mysummmercar_Data -> mywintercar_Data")
        except Exception as e:
            self.log_msg(f"Revert error: {e}", error=True)
            QMessageBox.critical(self, "Error", f"Revert failed:\n{e}")
            return

        self.cfg["last_action"] = "REVERTED"
        save_config(self.cfg)
        self.update_info_label()

        QMessageBox.information(self, "Reverted", "Names reverted successfully.")
        self.log_msg("Revert completed successfully.")

    def on_install_msc_clicked(self):
        if not self.game_path:
            QMessageBox.warning(self, "No Folder", "Select or auto-detect game folder first.")
            self.log_msg("MSC Loader install aborted: no game folder selected.", error=True)
            return

        zip_path = Path("loader\\MSC_Loader.zip")

        if not zip_path.exists():
            self.log_msg("MSC Loader zip not found!", error=True)
            QMessageBox.critical(
                self,
                "ZIP not found",
                "File MSC_Loader.zip not found.\n"
            )
            return

        answer = QMessageBox.question(
            self,
            "Install Loader",
            "All matching files will be REPLACED.\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            self.log_msg("User cancelled loader install.")
            return

        try:
            self.log_msg("Installing Loader..")

            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(self.game_path)

            self.log_msg("Loader successfully unpacked!")
            QMessageBox.information(self, "Success", "Loader installed!")

        except Exception as e:
            self.log_msg(f"Install error: {e}", error=True)
            QMessageBox.critical(self, "Error", f"Error says:\n{e}")


# ---------------------------------------------------------
# SPLASH + APP ENTRY
# ---------------------------------------------------------

def show_splash(app: QApplication):
    logo_path = Path("assets") / "logo.png"
    if not logo_path.exists():
        return None

    pix = QPixmap(str(logo_path))
    if pix.isNull():
        return None

    splash = QSplashScreen(pix)
    splash.setWindowFlag(Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()
    time.sleep(1.3)
    return splash


def main():
    app = QApplication(sys.argv)

    splash = show_splash(app)

    window = MWCFixerWindow()
    window.show()

    if splash:
        splash.finish(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
