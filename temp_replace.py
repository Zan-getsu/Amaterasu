import re

with open(r'm:\Projects\Amaterasu\web\templates\encode_profiles.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Replace CSS classes
html = html.replace('bs-input', 'form-input')
html = html.replace('bs-select', 'form-select')
html = html.replace('bs-btn bs-btn--primary', 'btn btn--primary')
html = html.replace('bs-btn bs-btn--outline', 'btn btn--ghost')
html = html.replace('bs-chip', 'chip')
html = html.replace('bs-slider', 'slider-input')
html = html.replace('bs-toggle__track', 'toggle-track')
html = html.replace('bs-toggle__thumb', 'toggle-thumb')
html = html.replace('bs-toggle', 'toggle-wrap')
html = html.replace('bs-split-layout__preview', 'encode-preview')
html = html.replace('bs-split-layout', 'encode-layout')
html = html.replace('bs-section-title', 'encode-title')
html = html.replace('bs-section-subtitle', 'encode-title-sub')
html = html.replace('class="bs-flex" style="justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;"', 'class="encode-header"')
html = html.replace('<div class="bs-flex" style="gap: 12px; flex-wrap: wrap; justify-content: flex-end;">', '<div class="encode-actions">')

# Replace FontAwesome icons with Lucide React styles
html = html.replace('class="fa-solid fa-upload"', 'data-lucide="upload" style="width:14px;height:14px;"')
html = html.replace('class="fa-solid fa-download"', 'data-lucide="download" style="width:14px;height:14px;"')
html = html.replace('class="fa-solid fa-check"', 'data-lucide="check" style="width:14px;height:14px;"')
html = html.replace('<i class="fa-solid fa-plus"></i>', '<i data-lucide="plus" style="width:14px;height:14px;"></i>')
html = html.replace('<i class="fa-solid fa-trash"></i>', '<i data-lucide="trash-2" style="width:14px;height:14px;"></i>')
html = html.replace('class="fa-solid fa-film"', 'data-lucide="film" style="width:14px;height:14px;"')
html = html.replace('class="fa-solid fa-music"', 'data-lucide="music" style="width:14px;height:14px;"')
html = html.replace('class="fa-solid fa-closed-captioning"', 'data-lucide="subtitles" style="width:14px;height:14px;"')
html = html.replace('class="fa-solid fa-globe"', 'data-lucide="globe" style="width:14px;height:14px;"')
html = html.replace('class="fa-solid fa-gear"', 'data-lucide="settings" style="width:14px;height:14px;"')
html = html.replace('class="fa-solid fa-copy"', 'data-lucide="copy" style="width:14px;height:14px;"')

with open(r'm:\Projects\Amaterasu\web\templates\encode_profiles.html', 'w', encoding='utf-8') as f:
    f.write(html)
