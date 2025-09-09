# predict_image.py

import os
import numpy as np
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image

# Load the trained model
MODEL_PATH = "models/circuit_classifier.h5"
model = load_model(MODEL_PATH)

# Class labels (must match training order)
class_labels = ['alternator', 'battery', 'portline']  # Update based on your folders

def predict_circuit_domain(img_path):
    try:
        img = image.load_img(img_path, target_size=(224, 224))
        img_array = image.img_to_array(img) / 255.0
        img_array = np.expand_dims(img_array, axis=0)

        prediction = model.predict(img_array)
        predicted_class = class_labels[np.argmax(prediction)]
        confidence = float(np.max(prediction))

        return {
            "domain": predicted_class,
            "confidence": round(confidence * 100, 2)
        }
    except Exception as e:
        return {
            "error": f"Prediction failed: {e}"
        }
