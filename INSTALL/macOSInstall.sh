#!/bin/bash
#This code install ffmeg on macOS
echo "This script will install ffmpeg on macOS"
echo "The installation can be if you have Homebrew or by source"
echo "Do you want to install ffmpeg on macOS by Homebrew? (y/n)"
read answer
if [ "$answer" == "y" ]; then
    echo "Verifying if Homebrew is installed..."
    which brew &> /dev/null
    if [ $? -ne 0 ]; then
        echo "Homebrew is not installed. Do you want to install it? (y/n)"
        read answer
        if [ "$answer" == "y" ]; then
            echo "Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        else
            echo "Homebrew installation cancelled."
            exit 1
        fi
    else
        echo "Homebrew is already installed."
    fi
    echo "Installing ffmpeg..."
    brew install ffmpeg
    if [ $? -eq 0 ]; then
        echo "ffmpeg installed successfully."
    else
        echo "ffmpeg installation failed."
        exit 1
    fi
else
    echo "Installing ffmpeg by source... (You need give sudo permission)"
    wget -P ~/Downloads/ https://evermeet.cx/ffmpeg/ffmpeg-7.1.1.zip
    cd ~/Downloads/
    unzip ffmpeg-7.1.1.zip
    rm ffmpeg-7.1.1.zip
    echo "The file is compiled and only needs running it"
    echo "Do you want to install ffmpeg by source? (y/n)"
    echo "./ffmpeg --version"
    echo "Warning: Some code are not compiled by default"
    echo "Do you want to add to zshrc or bashrc? (y/n)"
    read answer
    if [ "$answer" == "y" ]; then
        echo "Creating a hidden folder in your documents..."
        mkdir -p ~/Documents/.ffmpeg
        echo "Moving ffmpeg to the hidden folder..."
        mv ~/Downloads/ffmpeg-7.1.1 ~/Documents/.ffmpeg/
        echo "Adding ffmpeg to zshrc or bashrc..."
        if [ -f ~/.zshrc ]; then
            echo "Adding ffmpeg to zshrc..."
            echo "export PATH=\$PATH:~/Documents/.ffmpeg/ffmpeg" >> ~/.zshrc
        elif [ -f ~/.bashrc ]; then
            echo "Adding ffmpeg to bashrc..."
            echo "export PATH=\$PATH:~/Documents/.ffmpeg/ffmpeg-" >> ~/.bashrc
        else
            echo "No .zshrc or .bashrc file found."
            echo "Please add the following line to your shell configuration file:"
            echo "export PATH=\$PATH:~/Documents/.ffmpeg/ffmpeg"
            echo "You can run the following command to do it automatically:"
            echo "echo 'export PATH=\$PATH:~/Documents/.ffmpeg/ffmpeg' >> ~/.bash_profile"
            echo "or"
            echo "echo 'export PATH=\$PATH:~/Documents/.ffmpeg/ffmpeg' >> ~/.bashrc"
            echo "or"
            echo "echo 'export PATH=\$PATH:~/Documents/.ffmpeg/ffmpeg' >> ~/.zshrc"
        fi
        echo "ffmpeg installed successfully."
        echo "Please restart your terminal or run 'source ~/.zshrc' or 'source ~/.bashrc' to apply the changes."
        echo "You can run the following command to do it automatically:"
        echo "source ~/.zshrc"
    else
        echo "Installation cancelled."
    fi
fi