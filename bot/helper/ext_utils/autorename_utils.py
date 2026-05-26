import re
import logging
from bot import LOGGER

# Enhanced regex patterns for season and episode extraction
SEASON_EPISODE_PATTERNS = [
    # Standard patterns (S01E02, S01EP02)
    (re.compile(r'S(\d+)(?:E|EP)(\d+)', re.IGNORECASE), ('season', 'episode')),
    # Patterns with spaces/dashes (S01 E02, S01-EP02)
    (re.compile(r'S(\d+)[\s-]*(?:E|EP)(\d+)', re.IGNORECASE), ('season', 'episode')),
    # Full text patterns (Season 1 Episode 2)
    (re.compile(r'Season\s*(\d+)\s*Episode\s*(\d+)', re.IGNORECASE), ('season', 'episode')),
    # Patterns with brackets/parentheses ([S01][E02])
    (re.compile(r'\[S(\d+)\]\[E(\d+)\]', re.IGNORECASE), ('season', 'episode')),
    # Fallback patterns (S01 13, Episode 13)
    (re.compile(r'S(\d+)[^\d]*(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'(?:E|EP|Episode)\s*(\d+)', re.IGNORECASE), (None, 'episode')),
    # Final fallback (standalone number - very generic, maybe disable if causing false positives)
    # (re.compile(r'\b(\d+)\b'), (None, 'episode')) 
]

# Quality detection patterns
QUALITY_PATTERNS = [
    (re.compile(r'\b(\d{3,4}[pi])\b', re.IGNORECASE), lambda m: m.group(1)),  # 1080p, 720p
    (re.compile(r'\b(4k|2160p)\b', re.IGNORECASE), lambda m: "4k"),
    (re.compile(r'\b(2k|1440p)\b', re.IGNORECASE), lambda m: "2k"),
    (re.compile(r'\b(HDRip|HDTV|WEBRip|WEB-DL|BDRip|BluRay)\b', re.IGNORECASE), lambda m: m.group(1)),
    (re.compile(r'\b(4kX264|4kx265|x264|x265|HEVC)\b', re.IGNORECASE), lambda m: m.group(1)),
    (re.compile(r'\[(\d{3,4}[pi])\]', re.IGNORECASE), lambda m: m.group(1))  # [1080p]
]

def extract_season_episode(filename):
    """Extract season and episode numbers from filename"""
    for pattern, (season_group, episode_group) in SEASON_EPISODE_PATTERNS:
        match = pattern.search(filename)
        if match:
            season = match.group(1) if season_group else None
            episode = match.group(2) if episode_group else match.group(1)
            # Pad with zeros if they are just one digit
            if season and len(season) == 1:
                season = f"0{season}"
            if episode and len(episode) == 1:
                episode = f"0{episode}"
            return season, episode
    return None, None

def extract_quality(filename):
    """Extract quality information from filename"""
    for pattern, extractor in QUALITY_PATTERNS:
        match = pattern.search(filename)
        if match:
            quality = extractor(match)
            return quality
    return ""

def clean_title(filename):
    """Remove known patterns from the filename to extract the base title."""
    cleaned = filename
    # Strip extension
    import os
    cleaned, _ = os.path.splitext(cleaned)
    
    # Strip season/episode
    for pattern, _ in SEASON_EPISODE_PATTERNS:
        cleaned = pattern.sub('', cleaned)
        
    # Strip quality
    for pattern, _ in QUALITY_PATTERNS:
        cleaned = pattern.sub('', cleaned)
        
    # Strip common release group brackets
    cleaned = re.sub(r'\[.*?\]', '', cleaned)
    cleaned = re.sub(r'\(.*?\)', '', cleaned)
    
    # Strip leftover separators
    cleaned = re.sub(r'[_\-\.]+', ' ', cleaned)
    
    # Strip year if it's there
    cleaned = re.sub(r'\b(19|20)\d{2}\b', '', cleaned)
    
    return cleaned.strip()

def apply_autorename_template(filename: str, template: str) -> str:
    """
    Applies the autorename template to a filename.
    Variables supported: {title}, {season}, {episode}, {quality}
    """
    import os
    ext = os.path.splitext(filename)[1]
    
    season, episode = extract_season_episode(filename)
    quality = extract_quality(filename)
    title = clean_title(filename)
    
    # Prepare replacements
    replacements = {
        '{season}': season or '',
        '{episode}': episode or '',
        '{quality}': quality or '',
        '{title}': title or '',
        'Season': season or '',
        'Episode': episode or '',
        'QUALITY': quality or '',
        'TITLE': title or ''
    }
    
    formatted_name = template
    for placeholder, value in replacements.items():
        if not value:
            # If the value is empty, remove the placeholder and potential adjacent formatting 
            # (e.g. S{season}E{episode} -> if season is empty, we don't want SE01)
            # This is tricky without a real template engine. We just replace with empty string.
            formatted_name = formatted_name.replace(placeholder, "")
            # Also clean up stranded S or E if season/episode missing
            if placeholder == '{season}':
                formatted_name = re.sub(r'\bS(?=E\d+|\b)', '', formatted_name, flags=re.IGNORECASE)
            elif placeholder == '{episode}':
                formatted_name = re.sub(r'\bE(?=\b)', '', formatted_name, flags=re.IGNORECASE)
        else:
            formatted_name = formatted_name.replace(placeholder, value)
            
    # Clean up double spaces or floating hyphens resulting from empty replacements
    formatted_name = re.sub(r'\s+', ' ', formatted_name)
    formatted_name = re.sub(r'\s*-\s*$', '', formatted_name)
    formatted_name = re.sub(r'^\s*-\s*', '', formatted_name)
    formatted_name = formatted_name.strip()
    
    if not formatted_name:
        return filename
        
    return f"{formatted_name}{ext}"
