import logging
import re
import subprocess
from typing import List, Dict, Optional


class MangaVolumeMerger:
    """Handles the merging of manga chapters into volumes"""

    CHAPTER_PATTERNS = [
        r'(\d+)(?!.*\d)',  # last number is the chapter number
        r'[^\d]*(\d+)(?:\s*$|\s*v\d+)',  # 1, 001, etc.
        r'(?:^|\s)(\d+)(?:\s|$)',  # standalone numbers
    ]

    def __init__(self, chapters_per_volume: int = 10):
        self.chapters_per_volume = chapters_per_volume
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

    def group_chapters_into_volumes(self, files: List[str]) -> Dict[int, List[str]]:
        """Group chapter files into volumes"""
        chapter_files = []
        for f in files:
            try:
                chapter_num = self.extract_chapter_number(f)
                chapter_files.append((chapter_num, f))
            except ValueError as e:
                self.logger.warning(f"Skipping file: {e}")
                continue

        chapter_files.sort(key=lambda x: x[0])

        volumes = {}
        for i, (chapter_num, file_path) in enumerate(chapter_files):
            volume_num = (i // self.chapters_per_volume) + 1
            if volume_num not in volumes:
                volumes[volume_num] = []
            volumes[volume_num].append(file_path)

        return volumes

    def merge_chapters_to_volume(self, chapter_files: List[str], output_path: str) -> Optional[str]:
        """Convert CBZ to PDF using calibre"""
        try:
            # Basic conversion command with correct comic options
            cmd = [
                'ebook-convert',
                chapter_files[0],  # First file is always the input
                output_path,
                '--right2left',  # Correct option for manga
                '--dont-grayscale',  # Keep original colors
                '--disable-trim',  # Don't trim page borders
                '--keep-aspect-ratio',  # Maintain aspect ratio
                '--dont-sharpen',  # No sharpening needed for manga
                '--dont-normalize'  # No color normalization
            ]

            # Add additional files if there are more than one
            if len(chapter_files) > 1:
                for additional_file in chapter_files[1:]:
                    cmd.append(f'--input-additional="{additional_file}"')

            # Run the conversion
            self.logger.info(f"Running conversion command: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            return output_path

        except Exception as e:
            self.logger.error(f"Failed to convert chapters: {str(e)}")
            return None
