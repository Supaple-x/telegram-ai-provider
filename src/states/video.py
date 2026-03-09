from aiogram.fsm.state import State, StatesGroup


class VideoWizard(StatesGroup):
    """States for video generation wizard."""
    
    # Step 1: Choose mode (text-to-video / image-to-video)
    mode = State()

    # Step 1b: Choose model for image-to-video (Seedance / Kling O3)
    i2v_model = State()

    # Step 2: Aspect ratio (16:9 / 9:16 / 1:1)
    aspect_ratio = State()
    
    # Step 3: Duration (5s / 8s / 10s)
    duration = State()
    
    # Step 4: Resolution (720p / 1080p)
    resolution = State()
    
    # Step 5: Audio (yes / no)
    audio = State()
    
    # Step 6: Prompt input (or image for image-to-video)
    prompt = State()

    # Step 6b: AI style suggestions for image-to-video
    style_select = State()

    # Step 7: Confirm and AI prompt enhancement
    confirm = State()

    # Video-to-video specific states
    v2v_model = State()         # Choose Wan 2.2 / Kling O3
    v2v_video_upload = State()  # Waiting for user to send a video file
    v2v_strength = State()      # Wan 2.2 only: transformation strength
