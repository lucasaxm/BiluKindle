import logging
import os
import re
import shutil
import subprocess
import zipfile
from typing import List, Dict, Optional

from PIL import Image


class MangaVolumeMerger:
    """Handles the merging of manga chapters into volumes"""

    CHAPTER_PATTERNS = [
        r'(?:chapter|cap(?:i|í)tulo|cap)[^\d]*(\d+)',  # chapter 1, capitulo 1, cap 1
        r'[^\d]*(\d+)(?:\s*$|\s*v\d+)',  # 1, 001, etc.
        r'(?:^|\s)(\d+)(?:\s|$)',  # standalone numbers
    ]

    def __init__(self, chapters_per_volume: int = 10):
        self.chapters_per_volume = chapters_per_volume
        self.logger = logging.getLogger(__name__)
        self.supported_image_types = ('.jpg', '.jpeg', '.png')

    def extract_chapter_number(self, filename: str) -> int:
        """Extract chapter number from filename"""
        filename_lower = filename.lower()

        # Try patterns that look for specific keywords first
        for pattern in self.CHAPTER_PATTERNS:
            match = re.search(pattern, filename_lower)
            if match:
                return int(match.group(1))

        # If no matches found with patterns, look for any number
        numbers = re.findall(r'\d+', filename_lower)
        if numbers:
            # Try to find the most likely chapter number
            # Prefer numbers that come after known keywords
            for keyword in ['ch', 'cap', 'chapter']:
                if keyword in filename_lower:
                    pos = filename_lower.find(keyword)
                    for num in numbers:
                        num_pos = filename_lower.find(num)
                        if num_pos > pos:
                            return int(num)
            return int(numbers[0])

        raise ValueError(f"Could not extract chapter number from {filename}")

    def group_chapters_into_volumes(self, files: List[str]) -> Dict[int, List[str]]:
        """Group chapter files into volumes"""
        # Sort files by chapter number
        chapter_files = []
        for f in files:
            try:
                chapter_num = self.extract_chapter_number(f)
                chapter_files.append((chapter_num, f))
            except ValueError as e:
                self.logger.warning(f"Skipping file: {e}")
                continue

        chapter_files.sort(key=lambda x: x[0])

        # Group into volumes
        volumes = {}
        for i, (chapter_num, file_path) in enumerate(chapter_files):
            volume_num = (i // self.chapters_per_volume) + 1
            if volume_num not in volumes:
                volumes[volume_num] = []
            volumes[volume_num].append(file_path)

        return volumes

    def optimize_image(self, image_path: str) -> str:
        """Optimize image for Kindle display"""
        try:
            with Image.open(image_path) as img:
                # Convert to grayscale
                if img.mode != 'L':
                    img = img.convert('L')

                # Resize if too large (Kindle Paperwhite resolution: 1072x1448)
                max_width, max_height = 1072, 1448
                if img.width > max_width or img.height > max_height:
                    img.thumbnail((max_width, max_height), Image.LANCZOS)

                # Enhance contrast and sharpness
                from PIL import ImageEnhance
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(1.2)

                enhancer = ImageEnhance.Sharpness(img)
                img = enhancer.enhance(1.3)

                # Save optimized image
                optimized_path = image_path.replace('.', '_optimized.')
                img.save(optimized_path, 'JPEG', quality=85, optimize=True)
                return optimized_path

        except Exception as e:
            self.logger.error(f"Failed to optimize image {image_path}: {str(e)}")
            return image_path

    def extract_cbz(self, cbz_path: str, extract_dir: str) -> List[str]:
        """Extract images from CBZ file"""
        image_files = []
        try:
            with zipfile.ZipFile(cbz_path, 'r') as zip_ref:
                for file in zip_ref.namelist():
                    if file.lower().endswith(self.supported_image_types):
                        zip_ref.extract(file, extract_dir)
                        image_files.append(os.path.join(extract_dir, file))
        except Exception as e:
            self.logger.error(f"Failed to extract CBZ {cbz_path}: {str(e)}")
        return sorted(image_files)

    def merge_chapters_to_volume(self, chapter_files: List[str], output_path: str) -> Optional[str]:
        """Merge multiple chapters into a single volume"""
        temp_dir = f'temp_merge_{os.path.basename(output_path)}'
        os.makedirs(temp_dir, exist_ok=True)

        try:
            # Extract and process all images
            all_images = []
            for chapter_file in chapter_files:
                chapter_num = self.extract_chapter_number(chapter_file)
                chapter_dir = os.path.join(temp_dir, f'chapter_{chapter_num:03d}')
                os.makedirs(chapter_dir, exist_ok=True)

                # Extract images from CBZ
                images = self.extract_cbz(chapter_file, chapter_dir)

                # Optimize images
                optimized_images = []
                for img in images:
                    opt_img = self.optimize_image(img)
                    optimized_images.append(opt_img)

                all_images.extend(optimized_images)

            # Create AZW3
            if all_images:
                output_path = self.create_azw3(all_images, output_path)
            else:
                raise ValueError("No images found in chapters")

            return output_path

        except Exception as e:
            self.logger.error(f"Failed to merge chapters: {str(e)}")
            return None

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def create_azw3(self, image_paths: List[str], output_path: str) -> str:
        """Create AZW3 file from manga images"""
        html_path = f'{output_path}_temp.html'

        try:
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write('''
                <html>
                <head>
                    <style>
                        body { margin: 0; padding: 0; }
                        .manga-page { 
                            width: 100%; 
                            height: 100vh;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                        }
                        img { 
                            max-width: 100%; 
                            max-height: 100vh;
                            object-fit: contain;
                        }
                    </style>
                </head>
                <body>
                ''')

                for img_path in image_paths:
                    f.write(f'<div class="manga-page"><img src="{img_path}" /></div>\n')

                f.write('</body></html>')

            # Convert to AZW3 using calibre
            subprocess.run([
                'ebook-convert',
                html_path,
                output_path,
                '--output-profile=kindle_pw3',
                '--no-inline-toc',
                '--manga-style=right-to-left',
                '--keep-aspect-ratio',
                '--output-format=azw3',
                '--prefer-metadata-cover=false',
                '--use-auto-toc=false',
                '--page-breaks-before=/',
                '--compress-images=false'
            ], check=True)

            return output_path

        except Exception as e:
            self.logger.error(f"Failed to create AZW3: {str(e)}")
            raise

        finally:
            if os.path.exists(html_path):
                os.remove(html_path)
