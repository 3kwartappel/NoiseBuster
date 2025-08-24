
import sys
import os
import subprocess

def embed_text_on_video(input_file, output_file, text):
    # Ensure the output directory exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Construct the ffmpeg command
    command = [
        "ffmpeg",
        "-y",
        "-i",
        input_file,
        "-vf",
        f"drawtext=text='{text}':x=w-tw-10:y=h-th-10:fontsize=24:fontcolor=pink",
        "-c:a",
        "copy",
        output_file,
    ]

    try:
        # Execute the command
        subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"Successfully embedded text '{text}' into {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"Error embedding text: {e.stderr}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python embed_text.py <input_file> <output_file> <text>")
        sys.exit(1)
    
    input_video = sys.argv[1]
    output_video = sys.argv[2]
    text_to_embed = sys.argv[3]
    
    embed_text_on_video(input_video, output_video, text_to_embed)
