# utils.py
from pdf2image import convert_from_path
from django.conf import settings
import os

def pdf_to_images(pdf_path, output_folder):
    pages = convert_from_path(pdf_path, dpi=150)
    image_paths = []
    for i, page in enumerate(pages):
        image_name = f'page_{i + 1}.png'
        image_path = os.path.join(output_folder, image_name)
        page.save(image_path, 'PNG')
        image_paths.append(image_path)
    return image_paths
