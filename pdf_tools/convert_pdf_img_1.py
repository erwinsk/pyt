#Install dependencies
#pip install PyMuPDF Pillow
import fitz  # PyMuPDF
from PIL import Image
import os

def pdf_to_images(pdf_path, output_folder, scale=2.0):
    """
    Converts a PDF to images, saving each page as a separate image.
    :param pdf_path: Path to the input PDF file.
    :param output_folder: Folder to save the output images.
    :param scale: Scaling factor to control image resolution (1.0 = original, >1.0 = higher quality).
    :return: List of image paths.
    """
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    pdf_document = fitz.open(pdf_path)
    image_paths = []

    for page_num in range(len(pdf_document)):
        page = pdf_document[page_num]
        # Control image resolution via scale factor
        zoom_matrix = fitz.Matrix(scale, scale)  # This scales the page rendering
        pix = page.get_pixmap(matrix=zoom_matrix)
        image_path = os.path.join(output_folder, f"page_{page_num + 1}.png")
        pix.save(image_path)
        image_paths.append(image_path)

    pdf_document.close()
    return image_paths

def images_to_pdf(image_paths, output_pdf_path):
    """
    Combines a list of images into a single PDF.
    :param image_paths: List of image file paths.
    :param output_pdf_path: Path to save the output PDF file.
    """
    image_list = []
    for image_path in image_paths:
        image = Image.open(image_path)
        if image.mode == "RGBA":
            image = image.convert("RGB")  # Convert to RGB for compatibility with PDF
        image_list.append(image)

    image_list[0].save(output_pdf_path, save_all=True, append_images=image_list[1:])

def convert_pdf_to_pdf(input_pdf, output_pdf, scale=2.0):
    """
    Converts a PDF to images and back to a PDF, with control over image quality.
    :param input_pdf: Path to the input PDF file.
    :param output_pdf: Path to the output PDF file.
    :param scale: Scaling factor to control image quality.
    """
    temp_folder = "temp_images"
    print("Converting PDF to images...")
    image_paths = pdf_to_images(input_pdf, temp_folder, scale)
    
    print("Converting images back to PDF...")
    images_to_pdf(image_paths, output_pdf)

    # Cleanup temporary images
    for image_path in image_paths:
        os.remove(image_path)
    os.rmdir(temp_folder)

    print(f"Conversion completed. Output PDF: {output_pdf}")
    
def user_select_pdf():
    """
    Lists all PDFs in the current directory and prompts the user to select one.
    :return: Path to the selected PDF file.
    """
    current_folder = os.getcwd()
    pdf_files = [f for f in os.listdir(current_folder) if f.endswith(".pdf")]

    if not pdf_files:
        print("No PDF files found in the current directory.")
        return None

    print("Select a PDF to convert:")
    for i, pdf_file in enumerate(pdf_files, 1):
        print(f"{i}. {pdf_file}")

    choice = int(input("Enter the number of the PDF to convert: ")) - 1
    if 0 <= choice < len(pdf_files):
        return os.path.join(current_folder, pdf_files[choice])
    else:
        print("Invalid selection.")
        return None

def get_unique_filename(output_pdf):
    """
    Generates a unique filename by appending an index if the file already exists.
    :param output_pdf: Original output PDF path.
    :return: A unique file path.
    """
    base_name, ext = os.path.splitext(output_pdf)
    index = 1

    while os.path.exists(output_pdf):
        output_pdf = f"{base_name}_{index}{ext}"
        index += 1

    return output_pdf

if __name__ == "__main__":
    print("Welcome to PDF Converter!")
    selected_pdf = user_select_pdf()

    if selected_pdf:
        base_name = os.path.splitext(os.path.basename(selected_pdf))[0]
        output_pdf = f"{base_name}_converted.pdf"
        output_pdf = get_unique_filename(output_pdf)  # Ensure unique output filename
        scale_factor = 2  # Adjust this value to control image quality (1.0 for original quality)
        convert_pdf_to_pdf(selected_pdf, output_pdf, scale_factor)
    else:
        print("No valid PDF selected. Exiting...")
