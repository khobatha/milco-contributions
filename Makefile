update-data: 
	python pipeline/aggregate.py            # Run the data analysis script
	python pipeline/update_data_files.py  # Run the JSON update script
