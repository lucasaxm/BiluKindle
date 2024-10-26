import logging
import os
import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PyPDF2 import PdfMerger


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

    MAX_PDF_SIZE = 23 * 1024 * 1024  # 45MB to be safe (Kindle limit is 50MB)

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

    def convert_cbz_to_pdf(self, cbz_path: str, output_path: str) -> Optional[str]:
        """Convert a single CBZ file to PDF using calibre"""
        try:
            cmd = [
                'ebook-convert',
                cbz_path,
                output_path,
                '--right2left',
                '--dont-grayscale',
                '--disable-trim',
                '--keep-aspect-ratio',
                '--dont-sharpen',
                '--dont-normalize'
            ]

            subprocess.run(cmd, check=True)
            return output_path
        except Exception as e:
            self.logger.error(f"Failed to convert CBZ to PDF: {str(e)}")
            return None

    def merge_pdfs(self, pdf_files: List[str], output_path: str) -> Optional[str]:
        """Merge multiple PDF files into one"""
        try:
            merger = PdfMerger()
            for pdf in pdf_files:
                merger.append(pdf)

            merger.write(output_path)
            merger.close()
            return output_path
        except Exception as e:
            self.logger.error(f"Failed to merge PDFs: {str(e)}")
            return None

    def get_file_size(self, file_path: str) -> int:
        """Get file size in bytes"""
        return os.path.getsize(file_path)

    def create_range_string(self, start: int, end: int) -> str:
        """Create a chapter range string"""
        if start == end:
            return f"[{start}]"
        return f"[{start}-{end}]"

    def merge_chapters_to_volume(self, chapter_files: List[str], base_name: str) -> List[Tuple[str, str]]:
        """
        Convert and merge chapters into volumes based on size and chapter numbers
        Returns: List of tuples (file_path, chapter_range)
        """
        try:
            # Convert chapters to ChapterInfo objects
            chapters: List[ChapterInfo] = []
            temp_files: List[str] = []

            # First convert all CBZ to PDF and gather chapter info
            for file_path in chapter_files:
                chapter_num = self.extract_chapter_number(file_path)

                if file_path.lower().endswith('.cbz'):
                    temp_pdf = f"{os.path.splitext(file_path)[0]}_temp.pdf"
                    if self.convert_cbz_to_pdf(file_path, temp_pdf):
                        chapters.append(ChapterInfo(temp_pdf, chapter_num, is_temp=True))
                        temp_files.append(temp_pdf)
                else:
                    chapters.append(ChapterInfo(file_path, chapter_num))

            # Sort chapters by number
            chapters.sort(key=lambda x: x.chapter_number)

            final_volumes: List[Tuple[str, str]] = []
            current_merge: List[ChapterInfo] = []
            last_successful_merge: Optional[str] = None
            last_successful_range: Optional[str] = None

            for chapter in chapters:
                if not current_merge:
                    current_merge.append(chapter)
                    continue

                # Try to merge with existing
                temp_output = f"{base_name}_temp_merge_{len(current_merge)}.pdf"  # Add counter to avoid conflicts
                merge_files = [
                    last_successful_merge if last_successful_merge
                    else current_merge[0].file_path
                ]
                merge_files.append(chapter.file_path)

                if self.merge_pdfs(merge_files, temp_output):
                    merged_size = self.get_file_size(temp_output)

                    if merged_size <= self.MAX_PDF_SIZE:
                        # Merge successful and within size limits
                        if last_successful_merge and os.path.exists(last_successful_merge):
                            os.remove(last_successful_merge)
                        last_successful_merge = temp_output
                        current_merge.append(chapter)

                        range_str = self.create_range_string(
                            current_merge[0].chapter_number,
                            current_merge[-1].chapter_number
                        )
                        last_successful_range = range_str
                    else:
                        # Over size limit, save previous merge and start new
                        if last_successful_merge:
                            final_name = f"{base_name}{last_successful_range}.pdf"
                            os.rename(last_successful_merge, final_name)
                            final_volumes.append((final_name, last_successful_range))

                        # Start new merge with current chapter
                        current_merge = [chapter]
                        last_successful_merge = None
                        last_successful_range = None
                else:
                    self.logger.error(f"Failed to merge chapter {chapter.chapter_number}")

            # Handle remaining chapters
            if current_merge:
                if last_successful_merge:
                    range_str = self.create_range_string(
                        current_merge[0].chapter_number,
                        current_merge[-1].chapter_number
                    )
                    final_name = f"{base_name}{range_str}.pdf"
                    os.rename(last_successful_merge, final_name)
                    final_volumes.append((final_name, range_str))
                else:
                    # Single chapter remaining
                    range_str = self.create_range_string(
                        current_merge[0].chapter_number,
                        current_merge[0].chapter_number
                    )
                    final_name = f"{base_name}{range_str}.pdf"
                    if current_merge[0].is_temp:
                        os.rename(current_merge[0].file_path, final_name)
                    else:
                        self.merge_pdfs([current_merge[0].file_path], final_name)
                    final_volumes.append((final_name, range_str))

            # Cleanup temporary files
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass

            return final_volumes

        except Exception as e:
            self.logger.error(f"Failed to merge chapters: {str(e)}")
            return []
