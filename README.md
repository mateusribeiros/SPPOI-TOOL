# Title: 

## Abstract

## Installation

```
# Create a virtual environment for the dependencies
python -3.12 -m venv venv

# Activate virtual environment
source env/bin/activate //for macOS and Linux
env\Scripts\activate // for Windows

# Download dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# Download database
python manage.py migrate

# Run the prototype
python manage.py runserver

```

Access:
- `http://127.0.0.1:8000`
- `http://localhost:8000`

## Setup

It is mandatory to create a `.env` file in the project root following the .env.example and inserting an API key for HuggingFace.

Note: Replace <our_key> with your API key.

For more details on creating the HuggingFace API, please follow the instructions under this link[]()

```
# Autopreenchido / Autofilled
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_SECRET_KEY=

# Substitua <our_key> por chaves reais 
# Replace <our_key> for real keys
HF_API_TOKEN=<our_key>
```

## RAG Dataset

For validation of the articles used in RAG: SPPOI_TOOL/dataset_rag

## Pilot Study

The [pilot-study]([pilot-study) folder contains the results of the pilot study, along with the documentation submitted to the Research Ethics Committee.


