#!/usr/bin/env python3
import os
import sys
import torch
import logging
from typing import Optional, Tuple, Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.modeltokenizer import load_model_and_tokenizer
from src.globalvariables import Models, CPUModels, REPO_PATH

logger = logging.getLogger(__name__)


class ModelManager:
    """Model manager for reusing model instances."""

    _instance = None
    _model = None
    _tokenizer = None
    _model_name = None
    _device = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelManager, cls).__new__(cls)
        return cls._instance
    
    def load_model(self, model_name: str, country_code: str = "FR") -> Tuple[Any, Any]:
        """
        Load model and tokenizer if not already loaded or if different model requested.
        
        Parameters:
            model_name: Name of the model to load
            country_code: Country code for CO2 emissions calculation
            
        Returns:
            Tuple of (model, tokenizer)
        """
        if (self._model is not None and self._tokenizer is not None and 
            self._model_name == model_name):
            logger.info(f"Reusing existing model instance: {model_name}")
            return self._model, self._tokenizer
        
        if self._model is not None and self._model_name != model_name:
            logger.info(f"Switching from {self._model_name} to {model_name}")
            self.cleanup_model()
        
        logger.info(f"Loading model: {model_name}")
        try:
            self._model, self._tokenizer = load_model_and_tokenizer(model_name, REPO_PATH)
            if self._model is None or self._tokenizer is None:
                raise ValueError("Failed to load model or tokenizer")
            
            self._model_name = model_name
            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            
            logger.info(f"Successfully loaded model: {model_name}")
            return self._model, self._tokenizer
            
        except Exception as e:
            logger.error(f"Error loading model {model_name}: {e}")
            raise
    
    def get_model(self) -> Tuple[Any, Any]:
        """Get the currently loaded model and tokenizer.

        Returns:
            Tuple of (model, tokenizer)
        """
        if self._model is None or self._tokenizer is None:
            raise ValueError("No model loaded. Call load_model() first.")
        return self._model, self._tokenizer
    
    def get_model_name(self) -> Optional[str]:
        """Get the name of the currently loaded model.

        Returns:
            str: Name of the currently loaded model
        """
        return self._model_name
    
    def get_device(self) -> Optional[torch.device]:
        """Get the device of the currently loaded model.

        Returns:
            torch.device: Device of the currently loaded model
        """
        return self._device
    
    def cleanup_model(self):
        """Clean up the current model instance.

        Returns:
            None
        """
        if self._model is not None:
            logger.info(f"Cleaning up model: {self._model_name}")
            try:
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                
                del self._model
                del self._tokenizer
                
                import gc
                gc.collect()
                
                logger.info("Model cleanup completed")
                
            except Exception as e:
                logger.warning(f"Error during model cleanup: {e}")
            finally:
                self._model = None
                self._tokenizer = None
                self._model_name = None
                self._device = None
    
    def is_model_loaded(self) -> bool:
        """Check if a model is currently loaded.

        Returns:
            bool: True if a model is currently loaded
        """
        return self._model is not None and self._tokenizer is not None
    
    def get_model_info(self) -> dict:
        """Get information about the currently loaded model.

        Returns:
            dict: Information about the currently loaded model
        """
        return {
            "model_name": self._model_name,
            "device": str(self._device) if self._device else None,
            "is_loaded": self.is_model_loaded()
        }


model_manager = ModelManager()


def get_model_manager() -> ModelManager:
    """Get the global model manager instance.

    Returns:
        ModelManager: Global model manager instance
    """
    return model_manager


def load_model_once(model_name: str, country_code: str = "FR") -> Tuple[Any, Any]:
    """
    Convenience function to load a model using the global model manager.
    
    Parameters:
        model_name: Name of the model to load
        country_code: Country code for CO2 emissions calculation
        
    Returns:
        Tuple of (model, tokenizer)
    """
    return model_manager.load_model(model_name, country_code)


def cleanup_global_model():
    """Convenience function to cleanup the global model.

    Returns:
        None
    """
    model_manager.cleanup_model()


