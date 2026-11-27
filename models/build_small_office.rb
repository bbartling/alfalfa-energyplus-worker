# Regenerate models/doe_small_office_90_1_2013.idf inside nrel/openstudio:3.9.0.
#
#   docker run --rm -v "$PWD:/work" -w /work \
#     -e RUBYLIB=/usr/local/openstudio-3.9.0/Ruby \
#     -e GEM_PATH=/var/oscli/gems/ruby/3.2.0 \
#     nrel/openstudio:3.9.0 ruby models/build_small_office.rb
#
# The image's embedded CLI cannot mkdir its weather cache, so this uses
# system Ruby with the standards gem on disk. The result is the PNNL/DOE
# SmallOffice prototype for ASHRAE 90.1-2013, climate zone 4A.

require 'openstudio-standards'

std = Standard.build('90.1-2013_SmallOffice')
model = std.model_create_prototype_model('ASHRAE 169-2013-4A', '', '/tmp/small-office-sizing', false)
raise 'prototype build did not return a model' unless model.is_a?(OpenStudio::Model::Model)

translator = OpenStudio::EnergyPlus::ForwardTranslator.new
workspace = translator.translateModel(model)
destination = File.expand_path('models/doe_small_office_90_1_2013.idf', Dir.pwd)
workspace.save(destination, true)
puts "wrote #{destination} (#{File.size(destination)} bytes), floor area #{model.getBuilding.floorArea} m2"
