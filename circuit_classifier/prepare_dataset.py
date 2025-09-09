from tensorflow.keras.preprocessing.image import ImageDataGenerator

# Path to your training dataset
train_dir = "dataset/train"

# Image preprocessing and augmentation
datagen = ImageDataGenerator(
    rescale=1./255,           # Normalize pixel values
    validation_split=0.2      # Reserve 20% for validation
)

# Training data generator
train_gen = datagen.flow_from_directory(
    train_dir,
    target_size=(224, 224),   # Resize images
    batch_size=32,
    class_mode='categorical',
    subset='training'
)

# Validation data generator
val_gen = datagen.flow_from_directory(
    train_dir,
    target_size=(224, 224),
    batch_size=32,
    class_mode='categorical',
    subset='validation'
)
