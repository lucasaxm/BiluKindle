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
    chapter_number: int
    is_temp: bool = False


class MangaVolumeMerger:
    """Handles the merging of manga chapters into volumes"""

    CHAPTER_PATTERNS = [
        r'(\d+)(?!.*\d)',  # last number is the chapter number
        r'[^\d]*(\d+)(?:\s*$|\s*v\d+)',  # 1, 001, etc.
        r'(?:^|\s)(\d+)(?:\s|$)',  # standalone numbers
    ]

    MAX_FILE_SIZE = '100'  # 47MB to be safe (Bot limit is 50MB)

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def extract_chapter_number(self, filename: str) -> int:
        """Extract chapter number from filename"""
        filename_lower = filename.lower()

        for pattern in self.CHAPTER_PATTERNS:
            match = re.search(pattern, filename_lower)
            if match:
                return int(match.group(1))

        numbers = re.findall(r'\d+', filename_lower)
        if numbers:
            return int(numbers[0])

        raise ValueError(f"Could not extract chapter number from {filename}")

    def unzip_cbz(self, cbz_path: str, output_dir: str) -> str:
        """Unzip a CBZ file into a directory"""
        chapter_dir = os.path.join(output_dir, str(self.extract_chapter_number(cbz_path)))
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

    def parse_nav_file(self, epub_file: str) -> tuple[int, int]:
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

                    return min([int(chapter) for chapter in chapters]), max([int(chapter) for chapter in chapters])
                except etree.XMLSyntaxError as e:
                    raise f"Failed to parse nav.xhtml: {e}"

    def remove_directory_contents(self, directory: str):
        """Remove all contents of a directory"""
        for root, dirs, files in os.walk(directory, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

    def merge_chapters_to_volume(self, chapter_files: List[str], base_name: str) -> List[Tuple[str, str]]:
        """
        Convert and merge chapters into volumes based on size and chapter numbers
        Returns: List of tuples (file_path, chapter_range)
        """
        try:
            # Unzip CBZ files
            temp_dirs = [self.unzip_cbz(file, base_name) for file in chapter_files]

            # Convert to EPUB
            epub_files = self.convert_to_epub(base_name, f"{base_name}.epub")

            # Parse nav.xhtml to get chapter order
            chapter_ranges = [self.parse_nav_file(epub) for epub in epub_files]

            # Rename EPUB files based on chapter ranges
            final_volumes = []
            for epub, chapters in zip(epub_files, chapter_ranges):
                if chapters:
                    range_str = f"[{chapters[0]}-{chapters[1]}]" if chapters[1] > chapters[0] else f"[{chapters[0]}]"
                    final_name = f"{base_name} {range_str}.epub"
                    os.rename(epub, final_name)
                    final_volumes.append((final_name, range_str))

            # Cleanup temporary directories
            for temp_dir in temp_dirs:
                if os.path.exists(temp_dir):
                    self.remove_directory_contents(temp_dir)
                    shutil.rmtree(temp_dir)

            return final_volumes

        except Exception as e:
            self.logger.error(f"Failed to merge chapters: {str(e)}")
            return []
