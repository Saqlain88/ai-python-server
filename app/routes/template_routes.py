from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from app.services.image_service import ImageService
from app.models.template import Template
from app.utils.decorators import admin_required
from app import db
import uuid

templates = Blueprint('templates', __name__)

@templates.route('/templates', methods=['POST'])
@admin_required
def create_template():
    try:
        # Check if image file is present in request
        if 'image' not in request.files:
            return jsonify({'error': 'No image file uploaded'}), 400
            
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        # Ensure filename is secure
        filename = secure_filename(file.filename)
        
        # Get template data from form
        name = request.form.get('name')
        category = request.form.get('category')
        
        if not name:
            return jsonify({'error': 'Template name is required'}), 400

        # Upload image to Cloudinary
        try:
            image_service = ImageService()
            upload_result = image_service.upload_image(file)
            
            # Create new template
            template = Template(
                name=name,
                category=category
                thumbnail_url=upload_result['secure_url'],
                cloudinary_public_id=upload_result['public_id']
            )
            
            db.session.add(template)
            db.session.commit()
            
            return jsonify({
                'message': 'Template created successfully',
                'template': template.to_dict()
            }), 201
            
        except Exception as e:
            return jsonify({'error': f'Failed to upload image: {str(e)}'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@templates.route('/templates', methods=['GET'])
def get_templates():
    templates = Template.query.all()
    return jsonify([template.to_dict() for template in templates]), 200

@templates.route('/templates/<template_id>', methods=['GET'])
def get_template(template_id):
    template = Template.query.get_or_404(template_id)
    return jsonify(template.to_dict()), 200

@templates.route('/templates/<template_id>', methods=['DELETE'])
@admin_required
def delete_template(template_id):
    template = Template.query.get_or_404(template_id)
    
    # Delete image from Cloudinary if it exists
    if template.cloudinary_public_id:
        image_service = ImageService()
        image_service.delete_image(template.cloudinary_public_id)
    
    db.session.delete(template)
    db.session.commit()
    
    return jsonify({'message': 'Template deleted successfully'}), 200

@templates.route('/templates/<template_id>', methods=['PUT'])
@admin_required
def update_template(template_id):
    template = Template.query.get_or_404(template_id)
    
    # Update template data
    if 'name' in request.form:
        template.name = request.form['name']
        
    if 'category' in request.form:
        template.category = request.form['category']
        
    # Handle image update if present
    if 'image' in request.files:
        file = request.files['image']
        if file.filename != '':
            try:
                image_service = ImageService()
                # Delete old image if it exists
                if template.cloudinary_public_id:
                    image_service.delete_image(template.cloudinary_public_id)
                    
                # Upload new image
                upload_result = image_service.upload_image(file)
                template.thumbnail_url = upload_result['secure_url']
                template.cloudinary_public_id = upload_result['public_id']
                
            except Exception as e:
                return jsonify({'error': f'Failed to update image: {str(e)}'}), 500
    
    db.session.commit()
    return jsonify(template.to_dict()), 200