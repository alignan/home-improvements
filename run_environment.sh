#!/bin/bash

# create the virtual environment and install dependencies
set_environment() {
    # virtualenv venv
    # source venv/bin/activate
    pip install -r requirements.txt
}

set_environment