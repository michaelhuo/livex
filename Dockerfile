FROM python:3.13.9-slim
WORKDIR /app
COPY . .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt --root-user-action=ignore
EXPOSE $PORT
ENV STREAMLIT_ENV=production
CMD ["sh", "-c", "streamlit run app.py --server.address 0.0.0.0 --server.port $PORT --server.maxMessageSize 200"]