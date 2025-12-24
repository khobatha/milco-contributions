update-data: 
	python pipeline/ingest_clean.py	 # Run the data ingestion and cleaning script
	python pipeline/aggregate.py            # Run the data analysis script
	python pipeline/update_data_files.py  # Run the JSON update script
