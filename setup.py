from setuptools import setup, find_packages

setup(
    name="fashion-stt",
    version="1.0.0",
    description="Real-time English Speech-to-Text Module for Fashion Applications",
    author="Arena AI",
    packages=find_packages(),
    install_requires=[
        "vosk>=0.3.45",
        "fastapi>=0.110.0",
        "uvicorn>=0.28.0",
        "websockets>=12.0",
        "python-multipart>=0.0.9",
        "gTTS>=2.5.0"
    ],
    entry_points={
        "console_scripts": [
            "fashion-stt=fashion_stt.cli:main",
        ],
    },
    python_requires=">=3.9",
    classifiers=[
        "Intended Audience :: Developers",
        "Topic :: Multimedia :: Sound/Audio :: Speech",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)
