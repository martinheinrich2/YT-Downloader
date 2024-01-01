from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QComboBox, QProgressBar, QStyleFactory
from PySide6.QtCore import Slot, QRunnable, QThreadPool, QTimer, QObject, Signal, Qt
from PySide6.QtGui import QImage, QPixmap
from pytube import YouTube
from pytube.exceptions import VideoUnavailable, VideoPrivate, AgeRestrictedError, MembersOnly

import requests
import validators

import os
import sys
import traceback
import subprocess as sp
import shlex
import shutil
import json
from threading import Thread
import time
import tempfile
import platform

from mainwindow import Ui_MainWindow

# Test if ffmpeg and ffprobe are somewhere on the system and set the path
if shutil.which("ffmpeg"):
    FFMPEG_PATH = shutil.which("ffmpeg")
    print(f'Setting ffmpeg path to: {shutil.which("ffmpeg")}')
elif os.path.isfile('ffmpeg'):
    FFMPEG_PATH = 'ffmpeg'
else:
    print(f'FFMPEG is not found! Please install ffmpeg.')

if shutil.which("ffprobe"):
    FFPROBE_PATH = shutil.which("ffprobe")
    print(f'Setting ffprobe path to: {shutil.which("ffprobe")}')
elif os.path.isfile('ffprobe'):
    FFPROBE_PATH = 'ffprobe'
else:
    print(f'FFPROBE is not found. Please install ffprobe.')


class WorkerSignals(QObject):
    """
    Defines the signals available from a running worker thread.

    Supported signals are:

    finished: No data
    error: tuple (exctype, value, traceback.format_exc())
    result: object data returned from processing, anything
    progress: int indicating % progress
    """
    finished = Signal()
    error = Signal(tuple)
    result = Signal(object)
    progress = Signal(int)


class Worker(QRunnable):
    """
    Worker thread that runs the download

    Inherits from QRunnable to handle worker thread setup, signals and wrap-up.

    :param callback: The function callback to run on this worker thread. Supplied args and
                        kwargs will be passed through to the runner.
    :type callback: function
    :param args: Arguments to pass to the callback function
    :param kwargs: Keyword arguments to pass to the callback function
    """

    def __init__(self, fn, *args, **kwargs):
        super(Worker, self).__init__()
        # Store constructor arguments (re-used for processing)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        # And the callback to our kwargs
        self.kwargs['progress_callback'] = self.signals.progress

    @Slot()
    def run(self):
        """
        Initialise the runner function with passed args, kwargs. Checks for exception types.
        :return: None
        """
        # Retrieve args/kwargs here; and fire processing using them
        try:
            result = self.fn(*self.args, **self.kwargs)
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)  # return the result of the process
        finally:
            self.signals.finished.emit()  # Done


class MainWindow(QMainWindow):
    # Change init function
    def __init__(self, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)
        # Create variables
        self.ffmpeg_string = None
        self.video_stream = None
        self.audio_stream = None
        self.output_filename = None
        self.pct_completed = 0
        self.yt = None
        self.title = None
        self.streams = None
        self.url = None
        self.filepath = None
        self.resolutions = ["None"]
        self.video_resolutions = []
        self.videos = []
        self.audio = []
        self.cwd = os.getcwd()
        self.temp_folder = tempfile.TemporaryDirectory()
        self.threadpool = QThreadPool()

        # Load UI-MainWindow class
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.statusBar().showMessage('Paste link to Youtube video.', timeout=0)
        # Add progress bar with percentage as text and center alignment
        self.progress = self.ui.progressBar
        self.progress.setValue(self.pct_completed)
        self.progress.setFormat("%0.2f %%" % self.pct_completed)
        self.progress.setAlignment(Qt.AlignCenter)
        # Choose widget style "Fusion" to display text in progress bar on MacOS
        if platform.system() == "Darwin":
            self.progress.setStyle(QStyleFactory.create("Fusion"))
        # Create Combobox Widget
        self.combobox = self.ui.comboBox
        self.combobox.addItems(self.resolutions)

        # Create Download Button
        self.button = self.ui.downloadButton
        self.button.clicked.connect(self.download_manager)

        # Create Line Edit Widget accepting drops
        self.line_edit = self.ui.lineEdit
        self.line_edit.setAcceptDrops(True)
        self.line_edit.textChanged.connect(self.line_edit_changed)

        # Create Preview Image of Video
        self.image = QImage()
        self.image_label = self.ui.image_label

    @Slot()
    def line_edit_changed(self, url):
        """
        Handle signal textChanged from the lineEdit widget. It checks if a valid url was dropped into the lineEdit
        widget. It then tries to load the title, thumbnail and information about the available streams.
        :param url:
        :return: None
        """
        if validators.url(url):
            try:
                # Check if creating YouTube object is successful, connect progress callback to function
                # on_download_progress.
                self.yt = YouTube(url, on_progress_callback=self.on_download_progress,
                                  use_oauth=True, allow_oauth_cache=True)
                self.streams = self.yt.streams
            except AgeRestrictedError:
                self.statusBar().showMessage(f'Video is age restricted. Check terminal output.')
            except MembersOnly:
                self.statusBar().showMessage(f'Video is members only.')
            except VideoPrivate:
                self.statusBar().showMessage(f'Video is private.')
            except VideoUnavailable:
                self.statusBar().showMessage(f'Video is unavailable')
            else:
                thumbnail_url = self.yt.thumbnail_url
                self.title = self.yt.title
                try:
                    self.streams_p = self.yt.streams.filter(subtype='mp4',
                                                            file_extension='mp4').get_highest_resolution()
                except AgeRestrictedError:
                    self.statusBar().showMessage(f'Video is age restricted.')
                self.streams = self.yt.streams
                self.image.loadFromData(requests.get(thumbnail_url).content)
                self.image_label.setPixmap(QPixmap(self.image).scaledToWidth(331))
                for stream in self.streams:
                    self.video_resolutions.append(stream.resolution)
                    self.videos.append(stream)
                self.available_resolutions()
        else:
            self.statusBar().showMessage(f'URL error, please try again.', timeout=5000)
        return

    def download_manager(self) -> None:
        """
        The download manager gets the output folder and calls the download worker if an output folder exists.
        The get_save_folder dialog has to be separate from the worker thread, otherwise QT throws an error.
        You cannot update GUI components or widgets from a worker thread.
        :return: None
        """
        save_folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if save_folder:
            self.output_filename = os.path.join(save_folder, f'{self.title}.mp4')
            self.download_worker()
        else:
            self.statusBar().showMessage(f'No download path provided.', timeout=5000)
        return

    @Slot()
    def download_worker(self) -> str:
        """
        Is called by the download manager.
        The download worker calls the download video function and handles all the thread signals
        :return: worker finished status
        """
        # Gets called by the button clicked signal. Pass the function to execute.
        worker = Worker(self.download_video)
        worker.signals.result.connect(self.print_output)
        worker.signals.finished.connect(self.download_complete)
        worker.signals.progress.connect(self.progress_fn)
        # Execute threadpool
        self.threadpool.start(worker)
        return f'download worker finished.'

    @Slot()
    def download_video(self, progress_callback) -> str:
        """
        Is called by the download worker.
        Download video and audio stream from YouTube and store them in a temporary folder. Combine the video and audio
        files with ffmpeg and save the output in save_folder.
        :return: None
        """
        # Get itag from combobox text
        try:
            audio_itag = int(self.audio[0].split(":")[1])
        except IndexError:
            self.statusBar().showMessage('No audio stream available.', timeout=5000)
        try:
            video_itag = int(self.combobox.currentText().split(":")[1])
        except IndexError:
            self.statusBar().showMessage('No audio stream available.', timeout=5000)
        # Choose streams by itag
        self.video_stream = self.yt.streams.get_by_itag(video_itag)
        self.audio_stream = self.streams.get_by_itag(audio_itag)
        # Check if streams are available and start download of video and audio streams
        if self.video_stream:
            self.video_stream.download(output_path=self.temp_folder.name, filename=f'video.mp4')
        if self.audio_stream:
            self.audio_stream.download(output_path=self.temp_folder.name, filename=f'audio.mp3')
        # Emit progress callback signal to worker with the current download percentage
        progress_callback.emit(self.pct_completed)
        self.statusBar().showMessage(f'Downloading video ...', timeout=0)
        self.statusBar().showMessage(f'Merging video and audio streams...', timeout=0)
        # Create separate function for merging files
        # Start merging files with ffmpeg
        audio_filename = os.path.join(self.temp_folder.name, f'audio.mp3')
        video_filename = os.path.join(self.temp_folder.name, f'video.mp4')

        # Use FFprobe for counting the total number of frames
        ################################################################################
        # Execute ffprobe (to show streams), and get the output in JSON format
        # Actually counts packets instead of frames, but it is much faster
        # https://stackoverflow.com/questions/2017843/fetch-frame-count-with-ffmpeg/28376817#28376817
        # Get number of frames with ffprobe and store the result in a dictionary.
        ffprobe_string = f'ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets -of csv=p=0 -of json {video_filename}'
        data = sp.run(shlex.split(ffprobe_string), stdout=sp.PIPE).stdout
        dict = json.loads(data)  # Convert data from JSON string to dictionary
        tot_n_frames = float(dict['streams'][0]['nb_read_packets'])  # Get the total number of frames.

        # Execute FFmpeg as sub-process with stdout as a pipe. Redirect progress to stdout using -progress pipe:1
        # arguments. Create string to call ffmpeg with all required parameters.
        self.ffmpeg_string = f'ffmpeg -y -loglevel error -i {video_filename} -i {audio_filename} -codec:v copy -codec:a copy -progress pipe:1'
        # self.ffmpeg_string = f'ffmpeg -y -loglevel error -i {video_filename} -i {audio_filename} -codec: copy -progress pipe:1'
        string1 = shlex.split(self.ffmpeg_string)
        string1.append(f'{self.output_filename}')
        process = sp.Popen(string1, stdout=sp.PIPE)
        q = [0]  # We don't really need to use a Queue - use a list of of size 1
        # Initialize progress reader thread
        progress_reader_thread = Thread(target=self.progress_reader, args=(process, q))
        progress_reader_thread.start()  # Start the thread

        while True:
            if process.poll() is not None:
                break  # Break if FFmpeg sun-process is closed
            time.sleep(1)  # Sleep 1 second (do some work...)
            n_frame = q[0]  # Read last element from progress_reader - current encoded frame
            progress_percent = (n_frame / tot_n_frames) * 100  # Convert to percentage.
            self.progress.setValue(progress_percent)
            self.progress.setFormat("Merging ... %0.2f %%" % progress_percent)

        process.stdout.close()  # Close stdin pipe.
        progress_reader_thread.join()  # Join thread
        process.wait()  # Wait for FFmpeg sub-process to finish

        self.statusBar().showMessage(f'Finished download.', timeout=0)
        self.yt = None
        return f'Download complete.'

    def on_download_progress(self, stream, chunk, bytes_remaining) -> int:
        """
        Calculates the progress of the download and updates the progress bar.
        :param stream:
        :param chunk:
        :param bytes_remaining:
        :return: percent completed
        """
        total_size = stream.filesize
        bytes_downloaded = total_size - bytes_remaining
        self.pct_completed = bytes_downloaded / total_size * 100
        self.pct_completed = round(self.pct_completed, 2)
        self.progress.setValue(self.pct_completed)
        self.progress.setFormat("Downloading ... %0.2f %%" % self.pct_completed)
        return self.pct_completed

    def progress_reader(self, procs, q) -> None:
        while True:
            if procs.poll() is not None:
                break  # Break if FFmpeg sun-process is closed
            progress_text = procs.stdout.readline()  # Read line from the pipe

            # Break the loop if progress_text is None (when pipe is closed).
            if progress_text is None:
                break
            progress_text = progress_text.decode("utf-8")  # Convert bytes array to strings

            # Look for "frame=xx"
            if progress_text.startswith("frame="):
                frame = int(progress_text.partition('=')[-1])  # Get the frame number
                q[0] = frame  # Store the last sample
        return

    def progress_fn(self, n):
        print(f"Progress: {n}")
        return

    def print_output(self, s):
        print(f'Print output: {s}')
        return

    def download_complete(self):
        """
        Reset the progress bar.
        :return:
        """
        self.progress.setValue(0)
        self.progress.setFormat("Download complete!")
        return

    def dragEnterEvent(self, event) -> None:
        """
        Accept only URL as drag drop item. Clear line edit widget, if item enters widget.
        :param event:
        :return: None
        """
        if event.mimeData().hasUrls:
            event.accept()
            self.line_edit.setText("")
            self.resolutions = ["None"]
        else:
            event.ignore()
        return

    def dropEvent(self, event) -> None:
        """
        Should print the url dropped.
        :param event:
        :return:
        """
        if event.mimeData().hasUrls:
            self.statusBar().showMessage("Drop failed, try again slower.", timeout=5000)
        return

    def available_resolutions(self) -> None:
        """
        Find available resolutions for video and append them to list resolutions. Resolutions are displayed
        in combobox to choose resolution for download.
        :return: None
        """
        if self.yt.streams.filter(resolution="2160p"):
            self.resolutions.append(f'2160 itag:{self.yt.streams.filter(resolution="2160p").first().itag}')
        if self.yt.streams.filter(resolution="1440p"):
            self.resolutions.append(f'1440 itag:{self.yt.streams.filter(resolution="1440p").first().itag}')
        if self.yt.streams.filter(resolution="1080p"):
            self.resolutions.append(f'1080 itag:{self.yt.streams.filter(resolution="1080p").first().itag}')
        if self.yt.streams.filter(resolution="720p", adaptive=True):
            self.resolutions.append(
                f'720 itag:{self.yt.streams.filter(resolution="720p", adaptive=True).first().itag}')
        if self.yt.streams.filter(resolution="720p", adaptive=False):
            self.resolutions.append(
                f'720 p itag:{self.yt.streams.filter(resolution="720p", adaptive=False).first().itag}')
        if self.yt.streams.filter(resolution="480p", adaptive=False):
            self.resolutions.append(
                f'480 p itag:{self.yt.streams.filter(resolution="480p", adaptive=False).first().itag}')
        if self.yt.streams.filter(resolution="360p", adaptive=False):
            self.resolutions.append(
                f'360 p itag:{self.yt.streams.filter(resolution="360p", adaptive=False).first().itag}')
        # Filter only mp4 audio files and avoid "audio/webm" with acodec="opus"
        if self.yt.streams.filter(abr="160kbps", mime_type="audio/mp4"):
            self.audio.append(f'160kbps itag:{self.yt.streams.filter(abr="160kbps").first().itag}')
        if self.yt.streams.filter(abr="128kbps", mime_type="audio/mp4"):
            self.audio.append(f'128kbps itag:{self.yt.streams.filter(abr="128kbps").first().itag}')
        if self.yt.streams.filter(abr="70kbps", mime_type="audio/mp4"):
            self.audio.append(f'70kbps itag:{self.yt.streams.filter(abr="70kbps").first().itag}')
        if self.yt.streams.filter(abr="48kbps", mime_type="audio/mp4"):
            self.audio.append(f'48kbps itag:{self.yt.streams.filter(abr="48kbps").first().itag}')
        self.resolutions.remove("None")
        self.combobox.clear()
        self.combobox.addItems(self.resolutions)
        return


if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = MainWindow()
    widget.show()
    sys.exit(app.exec())
