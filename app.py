from flask import Flask, request, render_template, redirect, url_for, send_from_directory
import os
import time
import azure.cognitiveservices.speech as speechsdk
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics import TextAnalyticsClient
import logging
import requests
import jwt
from datetime import datetime, timedelta
import pandas as pd
import openpyxl

app = Flask(__name__)
base_url = os.environ.get("BASE_URL", "")
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Set up the subscription info for the Speech Service:
speech_key = "76a2206eec094ffdb63e43ddd642de9f" # Provided by Prasanna Sir, free trial version, key will expire around 4th Aug 2024
service_region = "eastus"
output_file = os.path.join(app.config['OUTPUT_FOLDER'], "output.txt")

# Set up logging
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(message)s')

# Global token and expiration time
token = None
token_expiration = None

def get_new_token():
    global token, token_expiration
    client_id = "0d067d59-d398-4e14-ba7a-96cd5edead39"
    client_secret = "nFD8Q~RCZNVeKqg5HBqQ3kaj6Fn2jjo8iQdRZbwm"
    resource = "https://datalab-qa.unilever.com"
    auth_url = f"https://login.microsoftonline.com/f66fae02-5d36-495b-bfe0-78a6ff9f8e6e/oauth2/v2.0/token"
    
    payload = {
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': f'{resource}/.default'
    }
    
    response = requests.post(auth_url, data=payload)
    response.raise_for_status()
    token = response.json()['access_token']
    decoded_token = jwt.decode(token, options={"verify_signature": False})
    token_expiration = datetime.fromtimestamp(decoded_token['exp'])

def is_token_expired():
    if not token or not token_expiration:
        return True
    return datetime.now() >= token_expiration - timedelta(minutes=5)

def transcribe_and_translate_continuous_from_file(audio_path, source_language, target_language, output_file):
    translation_config = speechsdk.translation.SpeechTranslationConfig(
        subscription=speech_key, region=service_region,
        speech_recognition_language=source_language,
        target_languages=(target_language,))
    audio_config = speechsdk.audio.AudioConfig(filename=audio_path)
    recognizer = speechsdk.translation.TranslationRecognizer(
        translation_config=translation_config, audio_config=audio_config)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("")

    def result_callback(evt):
        if evt.result.reason == speechsdk.ResultReason.TranslatedSpeech:
            output_text = f"""Recognized: {evt.result.text}\n{target_language.capitalize()} translation: {evt.result.translations[target_language]}\n"""
            with open(output_file, "a", encoding="utf-8") as f:
                f.write(output_text)
                print("Output saved to:", output_file)

    recognizer.recognized.connect(result_callback)

    done = False

    def stop_cb(evt):
        print('CLOSING on {}'.format(evt))
        nonlocal done
        done = True

    recognizer.session_started.connect(lambda evt: print('SESSION STARTED: {}'.format(evt)))
    recognizer.session_stopped.connect(stop_cb)
    recognizer.canceled.connect(stop_cb)

    recognizer.start_continuous_recognition()

    while not done:
        time.sleep(0.5)

    recognizer.stop_continuous_recognition()

# this is the function to call gpt4 - we are using Azure OpenAI GenAI gpt4 model 
def call_gpt_sdk(email, project_id, message):
    if is_token_expired():
        get_new_token()
        
    api_url = 'https://datalab-qa.unilever.com/genai/conversation'
    headers = {
        'Content-Type': 'application/json',
        'X-User-Email': email,
        'Authorization': f'Bearer {token}'
    }
    payload = {
        "project_id": project_id,
        "messages": [
            {
                "id": "1",
                "role": "user",
                "content": f"{message}",
                "date": "2024-03-28T06:19:05.041Z"
            }
        ],
        "gpt_version": "GPT-4"
    }
    try:
        res_data = requests.post(api_url, json=payload, headers=headers, verify=False)
        res_data.raise_for_status()
        return res_data.json()
    
    except requests.exceptions.HTTPError as err:
        return f"HTTP Error: {err}"
    except requests.exceptions.RequestException as err:
        return f"Request Exception: {err}"

@app.route(f"{base_url}/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if 'file' not in request.files:
            return "No file part"
        file = request.files['file']
        if file.filename == '':
            return "No selected file"
        source_language = request.form['source_language']
        target_language = request.form['target_language']
        if file and source_language and target_language:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(file_path)
            transcribe_and_translate_continuous_from_file(file_path, source_language, target_language, os.path.join(app.config['OUTPUT_FOLDER'], "output.txt"))
            
            logging.info(f"File uploaded: {file.filename}")
            logging.info(f"File processed: {file.filename}")

            return redirect(url_for('success', filename=file.filename))
    return render_template('index.html')

@app.route(f"{base_url}/success/<filename>")
def success(filename):
    return render_template('success.html', base_url=base_url, filename=filename)

@app.route(f"{base_url}/summarize", methods=["GET", "POST"])
def summarize():
    output_file = os.path.join(app.config['OUTPUT_FOLDER'], "output.txt")
    with open(output_file, "r", encoding="utf-8") as f:
        translated_text = f.read()

    email = "pranita.randive@unilever.com"
    project_id = "d2344ac6-cfe8-4c65-92ae-6b1583265a50"

    chunk_size = 2000  # Adjust based on API limits and performance
    chunks = [translated_text[i:i + chunk_size] for i in range(0, len(translated_text), chunk_size)]

    summary_response = []
    for chunk in chunks:
        response = call_gpt_sdk(email, project_id, f"summarize the following text - '{chunk}'")
        summary_response.append(response)

    summary = " ".join([resp['choices'][0]['messages'][0]['content'] if 'choices' in resp and len(resp['choices']) > 0 else "Summary not available" for resp in summary_response])

    prompt_response = None
    excel_file = os.path.join(app.config['OUTPUT_FOLDER'], "prompt_responses.xlsx")

    if request.method == "POST":
        prompt = request.form.get('prompt', '')

        if prompt:
            response = call_gpt_sdk(email, project_id, f"Using the following context - '{translated_text}'. Answer the following question - '{prompt}'")
            if 'choices' in response and len(response['choices']) > 0:
                prompt_response = response['choices'][0]['messages'][0]['content']
            else:
                prompt_response = "Response not available"

            # Read existing data
            if os.path.exists(excel_file):
                df = pd.read_excel(excel_file)
            else:
                df = pd.DataFrame(columns=['Question', 'Response'])

            # Append new data
            new_data = pd.DataFrame({'Question': [prompt], 'Response': [prompt_response]})
            df = pd.concat([df, new_data], ignore_index=True)

            # Save to Excel
            df.to_excel(excel_file, index=False)

    return render_template('summary.html', base_url=base_url, summary=summary, prompt_response=prompt_response, translated_text=translated_text)

@app.route(f"{base_url}/download_summary")
def download_summary():
    email = "pranita.randive@unilever.com"
    project_id = "d2344ac6-cfe8-4c65-92ae-6b1583265a50"

    output_file = os.path.join(app.config['OUTPUT_FOLDER'], "output.txt")
    with open(output_file, "r", encoding="utf-8") as f:
        translated_text = f.read()

    # Call GPT SDK to generate summary
    summary_response = call_gpt_sdk(email, project_id, f"summarize the following text - '{translated_text}'")
    summary = summary_response['choices'][0]['messages'][0]['content'] if 'choices' in summary_response and len(summary_response['choices']) > 0 else "Summary not available"

    # Generate a summary file
    summary_file = os.path.join(app.config['OUTPUT_FOLDER'], "summary.txt")
    with open(summary_file, "w", encoding="utf-8") as sf:
        sf.write(summary)

    return send_from_directory(app.config['OUTPUT_FOLDER'], "summary.txt", as_attachment=True)

@app.route(f"{base_url}/download_prompt_response")
def download_prompt_response():
    return send_from_directory(app.config['OUTPUT_FOLDER'], "prompt_responses.xlsx", as_attachment=True)

@app.route(f"{base_url}/download")
def download():
    return send_from_directory(app.config['OUTPUT_FOLDER'], "output.txt", as_attachment=True)

@app.route(f"{base_url}/statistics")
def statistics():
    try:
        with open('app.log', 'r') as log_file:
            lines = log_file.readlines()
        
        upload_count = 0
        process_count = 0

        for line in lines:
            if "File uploaded" in line:
                upload_count += 1
            elif "File processed" in line:
                process_count += 1

        return render_template('statistics.html', base_url=base_url, upload_count=upload_count, process_count=process_count)
    
    except Exception as e:
        return f"Error reading log file: {str(e)}"

if __name__ == "__main__":
    app.run(debug=True)

# Pranita Randive (ULIP '24 Intern, Digital R&D)