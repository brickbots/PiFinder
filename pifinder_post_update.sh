git submodule update --init --recursive
# sudo pip install -r ./python/ments.txt

# Set up migrations folder if it does not exist
if ! [ -d "~/PiFinder_data/migrations" ]
then
    mkdir ~/PiFinder_data/migrations
fi

# v1.x.x
# everying prior to selecitve migrations
if ! [ -f "~/PiFinder_data/migrations/v1.x.x" ]
then
    source ./migration_source/v1.x.x.sh
    touch ~/PiFinder_data/migrations/v1.x.x
fi

# v2.1.0
# Switch to Cedar
if ! [ -f "~/PiFinder_data/migrations/v2.1.0" ]
then
    source ./migration_source/v2.1.0.sh
    touch ~/PiFinder_data/migrations/v2.1.0
fi

# DONE
echo "Post Update Complete"

