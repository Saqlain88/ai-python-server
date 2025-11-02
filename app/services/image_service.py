import cloudinary
import cloudinary.uploader
import os
from typing import Optional

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

class ImageService:
    @staticmethod
    def upload_image(file, public_id: Optional[str] = None, folder: str = "templates") -> dict:
        """Upload an image to Cloudinary and return the response"""
        try:
            # Upload the image to Cloudinary
            upload_result = cloudinary.uploader.upload(
                file,
                public_id=public_id,
                folder=folder,
                overwrite=True
            )
            
            return {
                'secure_url': upload_result['secure_url'],
                'public_id': upload_result['public_id']
            }
        except Exception as e:
            print(f"Failed to upload image: {str(e)}")
            raise e

    @staticmethod
    def delete_image(public_id: str) -> bool:
        """Delete an image from Cloudinary"""
        try:
            result = cloudinary.uploader.destroy(public_id)
            return result.get('result') == 'ok'
        except Exception as e:
            print(f"Failed to delete image: {str(e)}")
            return False