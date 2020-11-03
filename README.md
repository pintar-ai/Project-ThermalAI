# To build portal you need to execute several step
1. change directory to portal
2. mkdir postgres_data
3. create production file (env.prod and env.prod.postgres)
4. docker-compose up --build
5. it will run on port 3000 on your machine


##### create new DB (need to execute this when start build from scratch) : `docker-compose exec thermal_ai python manage.py create_db`
##### seed DB with 1 admin and 1 device (need to execute this when start build from scratch): `docker-compose exec thermal_ai python manage.py seed_db`
##### push to background : `docker-compose up -d --build`
##### show logs :  `docker-compose logs -f -t thermal_ai`

### env.prod example
```python
FLASK_APP=qr_generator/main_app.py
FLASK_ENV=development
DATABASE_URL=postgresql://root:abcde12345@postgres:5432/thermal_ai
SQL_HOST=postgres
SQL_PORT=5432
DATABASE=thermal_ai
```

### env.prod.postgres example
```python
POSTGRES_USER=root
POSTGRES_PASSWORD=abcde12345
POSTGRES_DB=thermal_ai
```
