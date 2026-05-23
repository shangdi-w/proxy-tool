from setuptools import setup, find_packages

with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="proxy-pool",
    version="2.0.0",
    description="Global proxy scraping, validation & rotation tool — pentesting focused",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="proxy-pool",
    url="https://github.com/your-username/proxy-pool",
    packages=find_packages(),
    py_modules=["cli"],
    install_requires=[
        "aiohttp>=3.9",
        "beautifulsoup4>=4.12",
        "flask>=3.0",
        "requests[socks]>=2.31",
        "PySocks>=1.7",
        "click>=8.1",
        "mysql-connector-python>=8.0",
    ],
    entry_points={
        "console_scripts": [
            "proxy-pool=cli:cli",
        ],
    },
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "Topic :: Internet :: Proxy Servers",
        "Topic :: Security",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
