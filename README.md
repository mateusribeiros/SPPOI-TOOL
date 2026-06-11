# SPPOI Tool: An AI-Enhanced Tool to support the Recommendation of Integration Patterns for Software-Intensive System

This repository contains the local prototype and research artifacts of the SPPOI Tool. The project supports architects and integration developers during the analysis and planning of integration scenarios by combining structured technical input, Retrieval-Augmented Generation (RAG), prompt engineering, and Large Language Models.

## Abstract

Integration among Software-Intensive Information Systems (SISs) remains a relevant challenge in Software Engineering, especially due to the adoption of fragmented solutions, ad hoc integration strategies, and limited systematization of architectural decisions. Since integration provides the physical and logical means through which systems can exchange information, poorly planned integrations may also hinder interoperability. This paper presents the SPPOI Tool, a locally executed prototype that combines Large Language Models, Retrieval-Augmented Generation, and prompt engineering to support the analysis and planning of integration scenarios. The tool receives structured information about systems, interfaces, and integration styles, generating critical risks and technical recommendations. The evaluation was conducted through case studies with open-source projects and an exploratory empirical assessment with professionals. The results indicate potential to support risk identification and the organization of recommendations, although they also reveal limitations related to the quality of the information provided.

## Installation

```bash
# Create a virtual environment
python -3.12 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate      # macOS / Linux
.venv\Scripts\activate         # Windows

# Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Setup

Before starting the prototype, create a `.env` file in the project root. The simplest option is to copy `.env.example` and adjust the values.

```bash
copy .env.example .env        # Windows
cp .env.example .env          # macOS / Linux
```

Example configuration:

```env
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_SECRET_KEY=django-insecure-change-me
HF_API_TOKEN=hf_your_token_here
SPPOI_DEV_PERSIST_PROJECTS=True
SPPOI_AUTO_OPEN_BROWSER=True
```

Notes:

- `HF_API_TOKEN` is required for the technical analysis generation.
- `SPPOI_DEV_PERSIST_PROJECTS=True` helps preserve project data during local development and repeated testing.
- `SPPOI_AUTO_OPEN_BROWSER=True` opens the prototype automatically in the browser when `python manage.py runserver` is executed.
- If `DJANGO_DEBUG=True` and `DJANGO_SECRET_KEY` is not set, the project already uses a stable local fallback key. Even so, setting your own key is recommended.

### How to obtain a Django secret key

You can generate a valid Django secret key with the following command:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copy the generated value and paste it into `.env`:

```env
DJANGO_SECRET_KEY=your_generated_secret_key
```

### How to obtain a Hugging Face token

1. Create or sign in to your Hugging Face account.
2. Open the access tokens page.
3. Create a new User Access Token.
4. Copy the generated token.
5. Paste it into the `.env` file as the value of `HF_API_TOKEN`.

For this prototype, a `read` token is usually enough because the application performs inference and does not publish repositories.

Useful links:

- Hugging Face token documentation: https://huggingface.co/docs/hub/en/security-tokens
- Hugging Face access tokens page: https://huggingface.co/settings/tokens

## Running the Prototype

After the `.env` file is configured, run:

```bash
python manage.py migrate
python manage.py runserver
```

If `SPPOI_AUTO_OPEN_BROWSER=True`, the browser should open automatically at the local URL when the server starts.

## Repository Contents

The main application code is available in:

- `sppoi_tool/`: Django app containing the forms, views, templates, and analysis pipeline.
- `core/`: Django project configuration, including settings and URL routing.

## Research Artifacts

The project artifacts related to the study are organized as follows:

- `dataset_rag/`: markdown files used as the RAG dataset and scientific support base for the analysis pipeline.
- `experiments/empirical_evaluation/`: empirical evaluation materials and consolidated experiment organization.
- `experiments/case_investigations/`: case investigation materials and artifacts used in the study.

## License

This project is distributed under the terms of the [LICENSE](LICENSE).
