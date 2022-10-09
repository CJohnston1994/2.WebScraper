import os, json, psycopg2, boto3, datetime
import config as c
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base

base = declarative_base()

class DataHandler():
    def __init__(self):
        #aws resources        
        s3_session = boto3.Session(aws_access_key_id=c.S3_ACCESS,aws_secret_access_key =c.S3_SECRET)
        self.s3_client = s3_session.client('s3')
        self.s3_resource = s3_session.resource('s3')
        self.my_bucket = self.s3_resource.Bucket('hayes-travel-web-scraper')

        self.engine = create_engine(f"{c.DATABASE_TYPE}+{c.DBAPI}://{c.USER}:{c.PASSWORD}@{c.HOST}:{c.PORT}/{c.DATABASE}")


    def _upload_data(self, raw_data):
        '''
        Upload all data and check for duplicate entries
        '''
        for row in raw_data:
            file_name = os.path.join("raw_data", row["uuid"], 'data.json')
            self.s3_client.upload_file(file_name, 'hayes-travel-web-scraper', file_name)   
        
    def __send_data_to_rds(self, df: pd.DataFrame):
        self.engine.connect()
        df = pd.DataFrame.from_dict(df)
        df.to_sql(name='hayes_holiday', con=self.engine, if_exists='append')


    def __clean_and_normalize(self, data: list) -> pd.DataFrame:
        df = pd.DataFrame.from_dict(data)
        
        pd.to_datetime(df.loc[0, 'next_date'])
        df.drop_duplicates(subset =
            ['url',
            'human_id',
            'hotel',
            'area',
            'country',  
            'price',
            'group_size',
            'nights',
            'catering',
            'next_date']
            )

        return data

    def __upload_images(self, raw_data):
        os.chdir('images')
        for image in os.listdir():
            image_file_name = os.path.join("raw_data",raw_data["uuid"],image)
            self.s3_client.upload_file(image, 'hayes-travel-web-scraper', image_file_name)   

    def images_already_scraped(self) -> list:
        scraped_images = []
        bucket = self.s3_resource.Bucket('hayes-travel-web-scraper')
        for file in bucket.objects.filter():
            if 'data.json' in file.key:
                content = file.get()['Body']
                json_content = json.load(content)
                if type(json_content) is str:
                    json_content = json.loads(json_content)
                
                scraped_url = json_content["images"]
                scraped_images.append(scraped_url)
        return scraped_images

    def process_data(self, raw_data):
        df = self.__clean_and_normalize(raw_data)
        self._upload_data(df)
        self.__send_data_to_rds(df)
        

    def process_images(self, path):
        original_path = os.getcwd()
        os.chdir(path)
        self.__upload_images(self.my_bucket)
        os.chdir(original_path)

    def remove_expired(self):
        today = datetime.date.today().strftime("%Y%m%d")
        with psycopg2.connect(host=c.HOST, user=c.USER, password=c.PASSWORD, dbname=c.DATABASE, port=c.PORT) as conn:
            with conn.cursor() as curs:
                curs.execute(f'''
                            IF NOT EXISTS(SELECT *
                                          FROM INFORMATION_SCHEMA.TABLES
                                          WHERE TABLE_SCHEMA = 'public'
                                          AND TABLE_NAME = 'ExpiredHolidays);
                            CREATE TABLE ExpiredHolidays AS
                            SELECT * FROM hayes_holiday
                            WHERE nextdate < '{today}';
                            ELSE INSERT INTO ExpiredHolidays
                            VALUES (SELECT * FROM hayes_holiday
                                    WHERE nextdate < '{today}');
                            DELETE FROM hayes_holiday
                            WHERE nextdate < '{today}'                      
                ''')

    #def remove_duplicates(self):
