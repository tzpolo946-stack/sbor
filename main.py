import ctypes
import json
import math
import os
import random
import subprocess
import sys
import threading
import traceback
from PyQt6 import QtCore, QtGui, QtWidgets
from core import APPDATA_BASE, MINECRAFT_DIR, get_resource_path, get_versions_by_loader, start_minecraft
from modrinth import install_project, search_projects

try:
    from rpc import DiscordRPC
except Exception:
    DiscordRPC = None

CONFIG_FILE = os.path.join(APPDATA_BASE, "config.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"username": "Player", "loader": "Vanilla", "version": "PurpleVisuals (Fabric 26.2)", "ram": 4}


def save_config(data):
    try:
        os.makedirs(APPDATA_BASE, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        pass


def get_total_ram_gb():
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return max(2, round(stat.ullTotalPhys / (1024 ** 3)))
    else:
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return max(2, round((pages * page_size) / (1024 ** 3)))
        except Exception:
            return 8


class AmbientFrame(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.particles = [
            {
                "x": random.uniform(0.05, 0.95),
                "y": random.uniform(0.05, 0.95),
                "r": random.randint(90, 210),
                "vx": random.uniform(-0.0006, 0.0006),
                "vy": random.uniform(-0.0005, 0.0005),
                "phase": random.uniform(0, math.tau),
                "color": random.choice([(139, 92, 246), (192, 38, 211), (109, 40, 217)]),
            }
            for _ in range(14)
        ]
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.step_particles)
        self.timer.start(30)

    def step_particles(self):
        for p in self.particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["phase"] += 0.03
            if p["x"] < 0.0 or p["x"] > 1.0:
                p["vx"] *= -1
            if p["y"] < 0.0 or p["y"] > 1.0:
                p["vy"] *= -1
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        for p in self.particles:
            cx, cy = p["x"] * w, p["y"] * h
            alpha = int(42 + 18 * math.sin(p["phase"]))
            grad = QtGui.QRadialGradient(cx, cy, p["r"])
            r, g, b = p["color"]
            grad.setColorAt(0.0, QtGui.QColor(r, g, b, alpha))
            grad.setColorAt(1.0, QtGui.QColor(r, g, b, 0))
            painter.setBrush(grad)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawEllipse(QtCore.QPointF(cx, cy), p["r"], p["r"])


class SignalBridge(QtCore.QObject):
    status_signal = QtCore.pyqtSignal(str)
    progress_signal = QtCore.pyqtSignal(int)
    done_signal = QtCore.pyqtSignal()
    versions_signal = QtCore.pyqtSignal(list)
    catalog_signal = QtCore.pyqtSignal(list)
class PurpleLauncher(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.drag_pos = None
        self.cfg = load_config()
        self.discord = DiscordRPC() if DiscordRPC else None
        self.total_ram = get_total_ram_gb()
        self.max_safe_ram = max(2, self.total_ram - 2)
        self.current_cat = "mod"
        self.card_anims = []

        self.bridge = SignalBridge()
        self.bridge.status_signal.connect(self.update_status)
        self.bridge.progress_signal.connect(self.update_progress)
        self.bridge.done_signal.connect(self.on_launch_finished)
        self.bridge.versions_signal.connect(self.on_versions_loaded)
        self.bridge.catalog_signal.connect(self.render_catalog_items)

        self.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint)
        self.resize(1280, 720)

        self.init_ui()
        self.setup_animations()
        self.showMaximized()
        self.reload_versions_list()

    def init_ui(self):
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.container = AmbientFrame()
        self.container.setObjectName("MainContainer")
        root_layout.addWidget(self.container)

        main_layout = QtWidgets.QVBoxLayout(self.container)
        main_layout.setContentsMargins(36, 26, 36, 28)

        top_bar = QtWidgets.QHBoxLayout()
        brand = QtWidgets.QLabel("PURPLE LAUNCHER")
        brand.setObjectName("LogoTitle")
        top_bar.addWidget(brand)
        top_bar.addSpacing(30)

        self.btn_tab_home = QtWidgets.QPushButton("Главная")
        self.btn_tab_home.setObjectName("NavBtn")
        self.btn_tab_home.clicked.connect(lambda: self.switch_page(0))

        self.btn_tab_lib = QtWidgets.QPushButton("Библиотека")
        self.btn_tab_lib.setObjectName("NavBtn")
        self.btn_tab_lib.clicked.connect(self.open_library_tab)

        self.btn_tab_settings = QtWidgets.QPushButton("Настройки")
        self.btn_tab_settings.setObjectName("NavBtn")
        self.btn_tab_settings.clicked.connect(lambda: self.switch_page(2))

        top_bar.addWidget(self.btn_tab_home)
        top_bar.addWidget(self.btn_tab_lib)
        top_bar.addWidget(self.btn_tab_settings)
        top_bar.addStretch()

        btn_min = QtWidgets.QPushButton("-")
        btn_min.setObjectName("WinBtn")
        btn_min.setFixedSize(36, 36)
        btn_min.clicked.connect(self.showMinimized)

        btn_max = QtWidgets.QPushButton("[]")
        btn_max.setObjectName("WinBtn")
        btn_max.setFixedSize(36, 36)
        btn_max.clicked.connect(self.toggle_maximize)

        btn_close = QtWidgets.QPushButton("X")
        btn_close.setObjectName("CloseBtn")
        btn_close.setFixedSize(36, 36)
        btn_close.clicked.connect(self.close)

        top_bar.addWidget(btn_min)
        top_bar.addWidget(btn_max)
        top_bar.addWidget(btn_close)
        main_layout.addLayout(top_bar)

        self.pages = QtWidgets.QStackedWidget()
        main_layout.addWidget(self.pages, stretch=1)

        home_page = QtWidgets.QWidget()
        home_layout = QtWidgets.QVBoxLayout(home_page)
        home_layout.setContentsMargins(0, 24, 0, 14)

        self.banner = QtWidgets.QFrame()
        self.banner.setObjectName("BannerCard")
        self.banner.setProperty("theme", "purple")
        banner_layout = QtWidgets.QVBoxLayout(self.banner)
        banner_layout.setContentsMargins(32, 32, 32, 32)

        self.b_title = QtWidgets.QLabel("Сборка PurpleVisuals • Fabric 26.2")
        self.b_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #FFFFFF;")
        self.b_desc = QtWidgets.QLabel("Фирменная сборка с визуальными модами, шейдерами и оптимизацией.")
        self.b_desc.setObjectName("SubTitle")

        banner_layout.addWidget(self.b_title)
        banner_layout.addSpacing(8)
        banner_layout.addWidget(self.b_desc)
        banner_layout.addStretch()
        home_layout.addWidget(self.banner, stretch=1)
        home_layout.addSpacing(20)
        controls = QtWidgets.QHBoxLayout()
        self.nick_input = QtWidgets.QLineEdit()
        self.nick_input.setPlaceholderText("Никнейм игрока")
        self.nick_input.setText(self.cfg.get("username", "Player"))
        self.nick_input.setFixedHeight(50)
        self.nick_input.textChanged.connect(self.save_current_settings)

        self.loader_box = QtWidgets.QComboBox()
        self.loader_box.addItems(["Vanilla", "Fabric", "Forge", "NeoForge", "Quilt", "Установленные"])
        saved_loader = self.cfg.get("loader", "Vanilla")
        l_idx = self.loader_box.findText(saved_loader)
        if l_idx >= 0:
            self.loader_box.setCurrentIndex(l_idx)
        self.loader_box.setFixedSize(170, 50)
        self.loader_box.currentTextChanged.connect(self.on_loader_changed)

        self.version_box = QtWidgets.QComboBox()
        self.version_box.addItem("Загрузка версий...")
        self.version_box.setFixedSize(280, 50)
        self.version_box.currentTextChanged.connect(self.on_version_changed)

        self.btn_play = QtWidgets.QPushButton("ИГРАТЬ")
        self.btn_play.setObjectName("PlayBtn")
        self.btn_play.setFixedSize(230, 50)
        self.btn_play.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_play.clicked.connect(self.on_play_clicked)

        controls.addWidget(self.nick_input, stretch=1)
        controls.addSpacing(12)
        controls.addWidget(self.loader_box)
        controls.addSpacing(12)
        controls.addWidget(self.version_box)
        controls.addSpacing(12)
        controls.addWidget(self.btn_play)
        home_layout.addLayout(controls)

        lib_page = QtWidgets.QWidget()
        lib_layout = QtWidgets.QVBoxLayout(lib_page)
        lib_layout.setContentsMargins(0, 18, 0, 10)

        filter_bar = QtWidgets.QHBoxLayout()
        self.cat_btns = {}
        for cat_id, title in [("mod", "Моды"), ("resourcepack", "Ресурспаки"), ("modpack", "Сборки")]:
            b = QtWidgets.QPushButton(title)
            b.setObjectName("CatBtn")
            b.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, c=cat_id: self.select_category(c))
            filter_bar.addWidget(b)
            self.cat_btns[cat_id] = b

        filter_bar.addSpacing(16)
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Поиск по Modrinth (например: Sodium, Iris, Bare Bones)...")
        self.search_input.returnPressed.connect(self.run_catalog_search)
        filter_bar.addWidget(self.search_input, stretch=1)

        btn_search = QtWidgets.QPushButton("Найти")
        btn_search.setObjectName("InstallBtn")
        btn_search.setFixedHeight(40)
        btn_search.clicked.connect(self.run_catalog_search)
        filter_bar.addWidget(btn_search)
        lib_layout.addLayout(filter_bar)
        lib_layout.addSpacing(14)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        self.catalog_container = QtWidgets.QWidget()
        self.catalog_container.setStyleSheet("background: transparent;")
        self.catalog_list_layout = QtWidgets.QVBoxLayout(self.catalog_container)
        self.catalog_list_layout.setSpacing(10)
        self.catalog_list_layout.addStretch()
        scroll.setWidget(self.catalog_container)
        lib_layout.addWidget(scroll, stretch=1)

        settings_page = QtWidgets.QWidget()
        set_layout = QtWidgets.QVBoxLayout(settings_page)
        set_layout.setContentsMargins(10, 30, 10, 10)

        saved_ram = min(self.cfg.get("ram", 4), self.max_safe_ram)
        self.ram_label = QtWidgets.QLabel(
            f"Выделение оперативной памяти (ОЗУ): {saved_ram} ГБ (доступно на ПК: {self.total_ram} ГБ)"
        )
        self.ram_label.setStyleSheet("font-size: 17px; font-weight: bold;")

        self.ram_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.ram_slider.setMinimum(2)
        self.ram_slider.setMaximum(self.max_safe_ram)
        self.ram_slider.setValue(saved_ram)
        self.ram_slider.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.ram_slider.valueChanged.connect(self.on_ram_changed)

        path_info = QtWidgets.QLabel(f"Путь установки игры: {MINECRAFT_DIR}")
        path_info.setObjectName("SubTitle")

        btn_open_dir = QtWidgets.QPushButton("Открыть папку game_files")
        btn_open_dir.setObjectName("NavBtn")
        btn_open_dir.setStyleSheet("background: #23143D; border: 1px solid #5B21B6; padding: 12px;")
        btn_open_dir.clicked.connect(self.open_game_folder)

        set_layout.addWidget(self.ram_label)
        set_layout.addSpacing(12)
        set_layout.addWidget(self.ram_slider)
        set_layout.addSpacing(24)
        set_layout.addWidget(path_info)
        set_layout.addSpacing(10)
        set_layout.addWidget(btn_open_dir, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        set_layout.addStretch()

        self.pages.addWidget(home_page)
        self.pages.addWidget(lib_page)
        self.pages.addWidget(settings_page)

        self.status_label = QtWidgets.QLabel("Готов к запуску PurpleVisuals")
        self.status_label.setObjectName("SubTitle")
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setValue(0)

        main_layout.addSpacing(10)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.progress_bar)
    def open_library_tab(self):
        self.switch_page(1)
        self.select_category(self.current_cat)

    def select_category(self, cat_id):
        self.current_cat = cat_id
        for cid, btn in self.cat_btns.items():
            btn.setProperty("active", "true" if cid == cat_id else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.run_catalog_search()

    def run_catalog_search(self):
        query = self.search_input.text().strip()
        ver = self.version_box.currentText()
        loader = self.loader_box.currentText()
        self.update_status("Поиск в библиотеке Modrinth...")

        def worker():
            try:
                hits = search_projects(query, self.current_cat, ver, loader)
                self.bridge.catalog_signal.emit(hits)
                self.bridge.status_signal.emit(f"Найдено проектов: {len(hits)}")
            except Exception as e:
                self.bridge.status_signal.emit(f"Ошибка поиска: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def render_catalog_items(self, hits):
        self.card_anims.clear()
        while self.catalog_list_layout.count() > 1:
            item = self.catalog_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, hit in enumerate(hits):
            card = QtWidgets.QFrame()
            card.setObjectName("ModCard")
            row = QtWidgets.QHBoxLayout(card)
            row.setContentsMargins(16, 12, 16, 12)

            info = QtWidgets.QVBoxLayout()
            title = QtWidgets.QLabel(f"{hit.get('title', 'Без названия')}  •  ⬇ {hit.get('downloads', 0):,}")
            title.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF;")
            desc = QtWidgets.QLabel(hit.get("description", ""))
            desc.setObjectName("SubTitle")
            desc.setWordWrap(True)
            info.addWidget(title)
            info.addWidget(desc)

            btn_inst = QtWidgets.QPushButton("Установить")
            btn_inst.setObjectName("InstallBtn")
            btn_inst.setFixedSize(130, 38)
            btn_inst.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            pid = hit.get("project_id")
            btn_inst.clicked.connect(lambda _, p=pid, b=btn_inst: self.on_install_item(p, b))

            row.addLayout(info, stretch=1)
            row.addSpacing(12)
            row.addWidget(btn_inst)
            self.catalog_list_layout.insertWidget(self.catalog_list_layout.count() - 1, card)

            card.setMaximumHeight(0)
            anim = QtCore.QPropertyAnimation(card, b"maximumHeight")
            anim.setDuration(260)
            anim.setStartValue(0)
            anim.setEndValue(110)
            anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            self.card_anims.append(anim)
            QtCore.QTimer.singleShot(idx * 35, anim.start)

    def on_install_item(self, project_id, btn):
        btn.setEnabled(False)
        btn.setText("Загрузка...")
        ver = self.version_box.currentText()
        loader = self.loader_box.currentText()
        cat = self.current_cat

        def worker():
            try:
                msg = install_project(
                    project_id, cat, ver, loader, MINECRAFT_DIR,
                    on_status=lambda t: self.bridge.status_signal.emit(t)
                )
                self.bridge.status_signal.emit(msg)
            except Exception as e:
                self.bridge.status_signal.emit(f"Ошибка установки: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def save_current_settings(self):
        save_config({
            "username": self.nick_input.text().strip() or "Player",
            "loader": self.loader_box.currentText(),
            "version": self.version_box.currentText(),
            "ram": self.ram_slider.value(),
        })

    def on_ram_changed(self, v):
        self.ram_label.setText(f"Выделение оперативной памяти (ОЗУ): {v} ГБ (доступно на ПК: {self.total_ram} ГБ)")
        self.save_current_settings()

    def setup_animations(self):
        self.setWindowOpacity(0.0)
        self.fade_anim = QtCore.QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(450)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.fade_anim.start()

        glow = QtWidgets.QGraphicsDropShadowEffect(self.btn_play)
        glow.setColor(QtGui.QColor(192, 38, 211, 220))
        glow.setOffset(0, 0)
        self.btn_play.setGraphicsEffect(glow)

        self.glow_group = QtCore.QSequentialAnimationGroup(self)
        anim_up = QtCore.QPropertyAnimation(glow, b"blurRadius")
        anim_up.setDuration(1200)
        anim_up.setStartValue(10)
        anim_up.setEndValue(32)
        anim_down = QtCore.QPropertyAnimation(glow, b"blurRadius")
        anim_down.setDuration(1200)
        anim_down.setStartValue(32)
        anim_down.setEndValue(10)
        self.glow_group.addAnimation(anim_up)
        self.glow_group.addAnimation(anim_down)
        self.glow_group.setLoopCount(-1)
        self.glow_group.start()

    def switch_page(self, index):
        self.pages.setCurrentIndex(index)

    def on_loader_changed(self, loader_text):
        self.version_box.blockSignals(True)
        self.version_box.clear()
        self.version_box.addItem("Загрузка списка...")
        self.version_box.blockSignals(False)
        self.save_current_settings()
        self.reload_versions_list()

    def reload_versions_list(self):
        loader = self.loader_box.currentText()
        threading.Thread(target=lambda: self.bridge.versions_signal.emit(get_versions_by_loader(loader)), daemon=True).start()

    def on_versions_loaded(self, versions):
        saved_ver = self.cfg.get("version", "PurpleVisuals (Fabric 26.2)")
        self.version_box.blockSignals(True)
        self.version_box.clear()
        self.version_box.addItems(versions)
        idx = self.version_box.findText(saved_ver)
        if idx >= 0:
            self.version_box.setCurrentIndex(idx)
        self.version_box.blockSignals(False)
        self.on_version_changed(self.version_box.currentText())

    def on_version_changed(self, version_text):
        if not version_text or "Загрузка" in version_text:
            return
        loader = self.loader_box.currentText()
        if "PurpleVisuals" in version_text:
            self.b_title.setText("Сборка PurpleVisuals • Fabric 26.2")
            self.b_desc.setText("Фирменная сборка с визуальными модами, шейдерами и оптимизацией.")
            self.banner.setProperty("theme", "purple")
        elif loader in ("Fabric", "Forge", "NeoForge", "Quilt"):
            self.b_title.setText(f"{loader} • Minecraft {version_text}")
            self.b_desc.setText(f"Модифицированный клиент {loader} для версии {version_text}. Автоустановка при запуске.")
            self.banner.setProperty("theme", "modded")
        else:
            self.b_title.setText(f"Minecraft Java Edition • {version_text}")
            self.b_desc.setText(f"Официальный клиент версии {version_text}. Готов к загрузке и запуску.")
            self.banner.setProperty("theme", "vanilla")

        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.save_current_settings()

    def open_game_folder(self):
        os.makedirs(MINECRAFT_DIR, exist_ok=True)
        if os.name == "nt":
            os.startfile(MINECRAFT_DIR)
        else:
            subprocess.Popen(["xdg-open", MINECRAFT_DIR])

    def on_play_clicked(self):
        version = self.version_box.currentText()
        loader = self.loader_box.currentText()
        nick = self.nick_input.text().strip() or "Player"
        ram = self.ram_slider.value()
        self.save_current_settings()

        self.btn_play.setEnabled(False)
        self.btn_play.setText("ЗАГРУЗКА...")

        def worker():
            try:
                start_minecraft(
                    selected_version=version,
                    loader_type=loader,
                    username=nick,
                    ram_gb=ram,
                    on_status=lambda t: self.bridge.status_signal.emit(t),
                    on_progress=lambda p: self.bridge.progress_signal.emit(int(p * 100)),
                )
                if self.discord:
                    self.discord.set_in_game(f"{version} ({loader})", nick)
            except Exception as e:
                self.bridge.status_signal.emit(f"Ошибка: {e}")
            finally:
                self.bridge.done_signal.emit()

        threading.Thread(target=worker, daemon=True).start()

    def update_status(self, text):
        self.status_label.setText(text)

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def on_launch_finished(self):
        self.btn_play.setEnabled(True)
        self.btn_play.setText("ИГРАТЬ")

    def mousePressEvent(self, event):
        left = event.button() == QtCore.Qt.MouseButton.LeftButton
        if left and not self.isMaximized() and event.position().y() <= 75:
            self.drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.drag_pos is not None and not self.isMaximized():
            self.move(self.pos() + event.globalPosition().toPoint() - self.drag_pos)
            self.drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None


def handle_crash(exc_type, exc_value, exc_tb):
    with open("crash.log", "w", encoding="utf-8") as log:
        traceback.print_exception(exc_type, exc_value, exc_tb, file=log)


sys.excepthook = handle_crash

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    qss_path = get_resource_path("style.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    launcher = PurpleLauncher()
    launcher.show()
    sys.exit(app.exec())
