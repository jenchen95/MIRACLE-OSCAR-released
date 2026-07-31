"""
Utility functions for the OSCAR model.
"""
import os

def get_oscar_path():
    """
    Get the absolute path to the oscar package directory.
    
    Returns:
        str: Absolute path to the oscar package directory
    """
    return os.path.dirname(os.path.abspath(__file__))

def get_input_data_path():
    """
    Get the absolute path to the input_data directory.
    
    Returns:
        str: Absolute path to the input_data directory
    """
    return os.path.join(get_oscar_path(), 'input_data')

def get_data_file_path(relative_path):
    """
    Get the absolute path to a data file in the input_data directory.
    
    Args:
        relative_path (str): Path relative to the input_data directory
    
    Returns:
        str: Absolute path to the data file
    """
    return os.path.join(get_input_data_path(), relative_path)
