import logging
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from typing import List, Tuple

from lxml import etree


@dataclass
class ChapterInfo:
    file_path: str
    chapter_number: float
    is_temp: bool = False


def chapter_number_to_str(ch_n: float) -> str:
    return f"{int(ch_n)}" if ch_n.is_integer() else f"{ch_n}"


class MangaVolumeMerger:
    """Handles the merging of manga chapters into volumes"""

    CHAPTER_PATTERNS = [
        r'(\d+(\.\d+)?)(?!.*\d)',  # last number is the chapter number, including decimals
        r'[^\d]*(\d+(\.\d+)?)(?:\s*$|\s*v\d+)',  # 1, 001, 1.5, etc.
        r'(?:^|\s)(\d+(\.\d+)?)(?:\s|$)',  # standalone numbers, including decimals
    ]

    MAX_FILE_SIZE = '195'  # 47MB to be safe (Bot limit is 50MB)

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def extract_chapter_number(self, filename: str) -> float:
        """Extract chapter number from filename"""
        filename_lower = filename.lower()

        for pattern in self.CHAPTER_PATTERNS:
            match = re.search(pattern, filename_lower)
            if match:
                return float(match.group(1))

        numbers = re.findall(r'\d+(\.\d+)?', filename_lower)
        if numbers:
            return float(numbers[0])

        raise ValueError(f"Could not extract chapter number from {filename}")

    def unzip_cbz(self, cbz_path: str, output_dir: str) -> str:
        """Unzip a CBZ file into a directory"""
        chapter_str = chapter_number_to_str(self.extract_chapter_number(cbz_path))
        chapter_dir = os.path.join(output_dir, f"Chapter {chapter_str}")
        os.makedirs(chapter_dir, exist_ok=True)
        with zipfile.ZipFile(cbz_path, 'r') as zip_ref:
            zip_ref.extractall(chapter_dir)
        return chapter_dir

    def convert_to_epub(self, input_dir: str, output_file: str) -> List[str]:
        """Convert a directory of images to EPUB using KCC"""
        try:
            cmd = [
                'kcc-c2e',
                '-p', 'KPW5',
                '-m',
                '-u',
                '-g', '0.90',
                '--forcecolor',
                '-f', 'EPUB',
                '-o', output_file,
                '-b', '1',
                '--ts', self.MAX_FILE_SIZE,
                input_dir
            ]
            self.logger.info(f"Running command: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            base_name = os.path.splitext(output_file)[0]
            return [f"{base_name}.epub"] + [f"{base_name}_kcc{i}.epub" for i in range(100) if
                                            os.path.exists(f"{base_name}_kcc{i}.epub")]
        except Exception as e:
            self.logger.error(f"Failed to convert to EPUB: {str(e)}")
            return []

    def parse_nav_file(self, epub_file: str) -> tuple[float, float]:
        """Parse the nav.xhtml file in the EPUB to get the chapter order"""
        with zipfile.ZipFile(epub_file, 'r') as zip_ref:
            nav_path = next((f.filename for f in zip_ref.filelist if f.filename.endswith('nav.xhtml')), None)

            if nav_path is None:
                raise "nav.xhtml file not found in EPUB"

            with zip_ref.open(nav_path) as nav_file:
                try:
                    content = nav_file.read()
                    tree = etree.fromstring(content)

                    # Define namespaces and use them in the XPath expression
                    namespaces = {'xhtml': 'http://www.w3.org/1999/xhtml'}
                    chapters = tree.xpath('/xhtml:html/xhtml:body/xhtml:nav[1]/xhtml:ol/xhtml:li/xhtml:a/text()',
                                          namespaces=namespaces)
                    chapters = [ch for ch in chapters if ch.strip().upper() != "A"]
                    return min([self.extract_chapter_number(chapter) for chapter in chapters]), max(
                        [self.extract_chapter_number(chapter) for chapter in chapters])
                except etree.XMLSyntaxError as e:
                    raise f"Failed to parse nav.xhtml: {e}"

    def remove_directory_contents(self, directory: str):
        """Remove all contents of a directory"""
        for root, dirs, files in os.walk(directory, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

    def merge_chapters_to_volume(self, chapter_files: List[str], manga_title: str, pages_to_remove: List[str] = None) -> \
            List[Tuple[str, str]]:
        """
        Convert and merge chapters into volumes based on size and chapter numbers
        Returns: List of tuples (file_path, chapter_range)
        """
        base_name = os.path.join("downloads", manga_title)
        if pages_to_remove is None:
            pages_to_remove = []

        temp_dirs = []

        try:
            # Unzip CBZ files
            temp_dirs = [self.unzip_cbz(file, base_name) for file in chapter_files]

            # Remove specified pages
            for temp_dir in temp_dirs[:1]:
                for page in pages_to_remove:
                    page_path = os.path.join(temp_dir, page)
                    if os.path.exists(page_path):
                        os.remove(page_path)

            # Manually create the "A" directory and copy "cover.jpg" into it
            cover_photo_path = os.path.join("downloads", "cover.jpg")
            if os.path.exists(cover_photo_path):
                cover_dir = os.path.join(base_name, "A")
                os.makedirs(cover_dir, exist_ok=True)
                shutil.copy(cover_photo_path, os.path.join(cover_dir, "cover.jpg"))
                temp_dirs.append(cover_dir)

            # Convert to EPUB
            epub_files = self.convert_to_epub(base_name, f"{base_name}.epub")

            # Parse nav.xhtml to get chapter order
            chapter_ranges = [self.parse_nav_file(epub) for epub in epub_files]

            # Rename EPUB files based on chapter ranges
            final_volumes = []
            for epub, chapters in zip(epub_files, chapter_ranges):
                if chapters:
                    if chapters[1] > chapters[0]:
                        range_str = f"[{chapter_number_to_str(chapters[0])}-{chapter_number_to_str(chapters[1])}]"
                    else:
                        range_str = f"[{chapter_number_to_str(chapters[0])}]"
                    final_name = f"{base_name} {range_str}.epub"
                    os.rename(epub, final_name)
                    final_volumes.append((final_name, range_str))

            return final_volumes

        except Exception as e:
            self.logger.error(f"Failed to merge chapters: {str(e)}")
            return []

        finally:
            # Cleanup temporary directories
            for temp_dir in temp_dirs:
                if os.path.exists(temp_dir):
                    self.remove_directory_contents(temp_dir)
                    shutil.rmtree(temp_dir)

            # Cleanup base directory
            if os.path.exists(base_name):
                self.remove_directory_contents(base_name)
                shutil.rmtree(base_name)

    def extract_first_images(self, chapter_path: str, num_images: int) -> List[str]:
        """
        Extract the first `num_images` images from the given chapter.

        Args:
            chapter_path: Path to the chapter file (CBZ).
            num_images: Number of images to extract.

        Returns:
            List of file paths to the extracted images.
        """
        extracted_images = []

        with zipfile.ZipFile(chapter_path, 'r') as zip_ref:
            image_files = [f for f in zip_ref.namelist() if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            image_files.sort()  # Ensure the images are in order
            for image_file in image_files[:num_images]:
                extracted_path = os.path.join("downloads", os.path.basename(image_file))
                with open(extracted_path, 'wb') as image_out:
                    image_out.write(zip_ref.read(image_file))
                extracted_images.append(extracted_path)

        return extracted_images


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    merger = MangaVolumeMerger()
    filename = "Anima Regia_Vol. 4, Ch. 23_ Extra.cbz"
    chapter_number = merger.extract_chapter_number(filename)
    chapter_str = f"{int(chapter_number)}" if chapter_number.is_integer() else f"{chapter_number}"
    print(f"Extracted chapter number: {chapter_str}")
