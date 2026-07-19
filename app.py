import os
import subprocess
import requests
from flask import Flask, request, send_file

app = Flask(__name__)


def download_file(url, dest_path):
    """Télécharge un fichier depuis une URL vers un chemin local."""
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with open(dest_path, 'wb') as f:
        f.write(resp.content)


@app.route('/', methods=['GET'])
def health():
    # Simple endpoint pour vérifier que le serveur est en ligne
    return {'status': 'ok'}, 200


@app.route('/create-video', methods=['POST'])
def create_video():
    try:
        data = request.json

        if not data or 'images' not in data:
            return {'error': "Le champ 'images' est manquant dans le body"}, 400

        images = sorted(data['images'], key=lambda x: x['name'])

        # Compatible avec un champ 'audio_url' unique OU un tableau 'audios'
        audios = sorted(data.get('audios', []), key=lambda x: x['name'])
        single_audio_url = data.get('audio_url')

        os.makedirs('/tmp/work', exist_ok=True)

        # Téléchargement des images
        for img in images:
            dest = f"/tmp/work/{img['name']}"
            download_file(img['url'], dest)

        # Téléchargement de l'audio (tableau ou url unique)
        audio_files = []
        if single_audio_url:
            dest = "/tmp/work/audio_0.mp3"
            download_file(single_audio_url, dest)
            audio_files.append(dest)
        else:
            for aud in audios:
                dest = f"/tmp/work/{aud['name']}"
                download_file(aud['url'], dest)
                audio_files.append(dest)

        n = len(images)
        if n == 0:
            return {'error': "Aucune image fournie"}, 400

        video_config = data.get('video_config', {})
        width = video_config.get('width', 1920)
        height = video_config.get('height', 1080)

        # --- Étape 1 : chaque image devient un petit clip vidéo, un par un ---
        clip_paths = []
        for idx, img in enumerate(images):
            duration = img.get('duration', 3)
            src = f"/tmp/work/{img['name']}"
            clip = f"/tmp/work/clip_{idx:04d}.mp4"
            cmd = (
                f'ffmpeg -y -loop 1 -t {duration} -i "{src}" '
                f'-vf "scale={width}:{height}:force_original_aspect_ratio=increase,'
                f'crop={width}:{height},setsar=1" '
                f'-c:v libx264 -crf 20 -preset veryfast -pix_fmt yuv420p "{clip}"'
            )
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                return {'error': f"Échec sur l'image {img['name']}: {result.stderr}"}, 500
            clip_paths.append(clip)

        # --- Étape 2 : concaténation des clips (légère, sans ré-encodage) ---
        concat_list_path = '/tmp/work/concat_list.txt'
        with open(concat_list_path, 'w') as f:
            for clip in clip_paths:
                f.write(f"file '{clip}'\n")

        video_only_path = '/tmp/work/video_only.mp4'
        concat_cmd = (
            f'ffmpeg -y -f concat -safe 0 -i "{concat_list_path}" '
            f'-c copy "{video_only_path}"'
        )
        result = subprocess.run(concat_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            return {'error': f"Échec de la concaténation vidéo: {result.stderr}"}, 500

        # --- Étape 3 : ajout de l'audio (optionnel) ---
        output_path = '/tmp/work/output.mp4'

        if audio_files:
            audio_list_path = '/tmp/work/audio_list.txt'
            with open(audio_list_path, 'w') as f:
                for a in audio_files:
                    f.write(f"file '{a}'\n")

            audio_only_path = '/tmp/work/audio_only.m4a'
            audio_concat_cmd = (
                f'ffmpeg -y -f concat -safe 0 -i "{audio_list_path}" '
                f'-c:a aac -b:a 192k "{audio_only_path}"'
            )
            result = subprocess.run(audio_concat_cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                return {'error': f"Échec de la concaténation audio: {result.stderr}"}, 500

            mux_cmd = (
                f'ffmpeg -y -i "{video_only_path}" -i "{audio_only_path}" '
                f'-c:v copy -c:a copy -shortest "{output_path}"'
            )
            result = subprocess.run(mux_cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                return {'error': f"Échec du mixage audio/vidéo: {result.stderr}"}, 500
        else:
            output_path = video_only_path

        return send_file(output_path, mimetype='video/mp4')

    except requests.exceptions.RequestException as e:
        return {'error': f"Erreur de téléchargement: {str(e)}"}, 500
    except KeyError as e:
        return {'error': f"Champ manquant dans le JSON: {str(e)}"}, 400
    except Exception as e:
        return {'error': f"Erreur inattendue: {str(e)}"}, 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
