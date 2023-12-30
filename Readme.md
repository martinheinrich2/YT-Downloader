# YouTube downloader

You can drag and drop a YouTube URL into the program and it will read the
metadata and display the available resolutions.  
You can choose the resolution to download. YouTube has two kinds of streams,
adaptive and progressive.  
YouTube supports DASH (Dynamic Adaptive Streaming over HTTP). As a result
adaptive streams have separate video and audio codec, resulting in a video and
audio file after download. You have to merge them into a single file.  
Progressive streams already contain video and audio in a single file.  
It uses QThreadPool with QRunnable to prevent freezing the application while
downloading and merging videos. Since the GUI application has a main thread that
runs the event loop and GUI, any longer task will freeze the GUI. QThread
prevents this.

### Functions
- drag and drop YouTube video URL into entry field
- read metadata and display the title, available resolutions and a thumbnail
- download single video and audio file or separate video and audio files and
merge them into one file.
- display download and merging progress

### Technologies used

- Pyside6
- pytube


### Usage
You need ffmpeg and ffprobe installed on your system. They are used to merge video
and audio stream.
