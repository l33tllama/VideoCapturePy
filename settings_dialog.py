from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    def __init__(
        self, current_settings, video_devices=None, audio_devices=None, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(350)

        self.settings = current_settings.copy()
        self.video_devices = video_devices or []
        self.audio_devices = audio_devices or []

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # Video Device Selector
        self.video_dev_combo = QComboBox()
        self.video_dev_combo.setEditable(True)
        for name, dev_id in self.video_devices:
            self.video_dev_combo.addItem(f"{name} ({dev_id})", dev_id)

        # Set current selection
        current_video = self.settings.get("video_dev", "")
        index = self.video_dev_combo.findData(current_video)
        if index != -1:
            self.video_dev_combo.setCurrentIndex(index)
        else:
            self.video_dev_combo.setEditText(current_video)

        # Audio Device Selector
        self.audio_dev_combo = QComboBox()
        self.audio_dev_combo.setEditable(True)
        for name, dev_id in self.audio_devices:
            self.audio_dev_combo.addItem(f"{name} ({dev_id})", dev_id)

        # Set current selection
        current_audio = self.settings.get("audio_dev", "")
        index = self.audio_dev_combo.findData(current_audio)
        if index != -1:
            self.audio_dev_combo.setCurrentIndex(index)
        else:
            self.audio_dev_combo.setEditText(current_audio)

        self.res_edit = QLineEdit(self.settings.get("res", ""))
        self.fps_edit = QLineEdit(self.settings.get("fps", ""))

        # Input Format Selector (v4l2: mjpeg, yuyv422, rawvideo, etc.)
        self.input_format_combo = QComboBox()
        self.input_format_combo.setEditable(True)
        self.input_format_combo.addItems(["", "mjpeg", "yuyv422", "rawvideo"])
        current_input_fmt = self.settings.get("input_format", "")
        self.input_format_combo.setCurrentText(current_input_fmt)

        # Quality Selector
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["Low", "Medium", "High"])
        current_quality = self.settings.get("quality", "High")
        self.quality_combo.setCurrentText(current_quality)

        form_layout.addRow("Video Device:", self.video_dev_combo)
        form_layout.addRow("Audio Device:", self.audio_dev_combo)
        form_layout.addRow("Resolution:", self.res_edit)
        form_layout.addRow("FPS:", self.fps_edit)
        form_layout.addRow("Input Format:", self.input_format_combo)
        form_layout.addRow("Quality Preset:", self.quality_combo)

        layout.addLayout(form_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_settings(self):
        video_dev = self.video_dev_combo.currentData()
        if video_dev is None:  # Use text if not found in data
            video_dev = self.video_dev_combo.currentText()

        audio_dev = self.audio_dev_combo.currentData()
        if audio_dev is None:
            audio_dev = self.audio_dev_combo.currentText()

        return {
            "video_dev": video_dev,
            "audio_dev": audio_dev,
            "res": self.res_edit.text(),
            "fps": self.fps_edit.text(),
            "input_format": self.input_format_combo.currentText().strip(),
            "quality": self.quality_combo.currentText(),
            "video_fmt": self.settings.get("video_fmt", ""),
            "audio_fmt": self.settings.get("audio_fmt", ""),
        }
