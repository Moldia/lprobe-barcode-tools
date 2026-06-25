FROM python:3.11-slim

ENV USER=appuser
ENV HOME=/home/$USER
ENV GRADIO_TEMP_DIR=$HOME/app/temp
ENV GRADIO_SERVER_NAME=0.0.0.0

RUN useradd -m -u 1000 $USER

WORKDIR $HOME/app

RUN apt-get update && apt-get install --no-install-recommends -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt $HOME/app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py $HOME/app/app.py
COPY main.py $HOME/app/main.py

RUN mkdir -p $GRADIO_TEMP_DIR \
    && chown -R $USER:$USER $HOME

USER $USER

EXPOSE 7860

CMD ["python", "main.py"]
